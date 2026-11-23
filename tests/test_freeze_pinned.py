"""A complete freeze is never re-used silently when its cases row or policy changed (CA-16, supervisor's guide of
21 Nov 2026: "changed refs cause an explicit refusal or a deliberate new version"). Standard library only.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import freeze_case as fc

ROW = {"case_id": "AF-01", "set": "pilot", "repo": "airflow", "pr_number": "6216", "jira_keys": "AIRFLOW-1",
       "decision_cutoff_utc": "2019-10-01T11:40:43Z", "head_sha": "h" * 40, "base_sha": "b" * 40}


def collect(row, case_dir):
    src = case_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)
    for rel in fc.MANDATORY:
        (case_dir / rel).write_text(f"{rel}\n", encoding="utf-8")
    _, sha, _ = fc.policy_for(row["repo"])
    (case_dir / fc.POLICY_SNAPSHOT).write_bytes(fc.policy_for(row["repo"])[0].read_bytes())
    (case_dir / "case.yaml").write_text(f"case_id: {row['case_id']}\npr_number: {row['pr_number']}\n"
                                        f"decision_cutoff_utc: {row['decision_cutoff_utc']}      # merged_at\n",
                                        encoding="utf-8")
    return {"mandatory": [], "refs": {"policy_sha256": sha, "head_at_merge": row["head_sha"],
                                      "base_at_merge": row["base_sha"], "merge_commit_sha": "m" * 40}}


class PinnedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_freeze(self, row, **kw):
        kw.setdefault("allow_draft", True)
        with mock.patch.object(fc, "collect", side_effect=collect), \
                contextlib.redirect_stdout(io.StringIO()):
            return fc.freeze(dict(row), self.out, **kw)

    def test_unchanged_row_is_skipped(self):
        self.assertEqual(self.run_freeze(ROW), "frozen")
        self.assertEqual(self.run_freeze(ROW), "skipped")

    def test_changed_head_is_refused_and_nothing_changes(self):
        self.run_freeze(ROW)
        before = (self.out / "AF-01" / "manifest.json").read_bytes()
        with self.assertRaises(SystemExit) as e:
            self.run_freeze(dict(ROW, head_sha="x" * 40))
        self.assertIn("head_sha", str(e.exception))
        self.assertIn("--refresh", str(e.exception))
        self.assertEqual((self.out / "AF-01" / "manifest.json").read_bytes(), before)

    def test_changed_cutoff_or_pr_is_refused(self):
        self.run_freeze(ROW)
        for change in ({"decision_cutoff_utc": "2019-10-02T00:00:00Z"}, {"pr_number": "9999"}):
            with self.assertRaises(SystemExit) as e:
                self.run_freeze(dict(ROW, **change))
            self.assertIn(next(iter(change)), str(e.exception))

    def test_changed_policy_is_refused(self):
        self.run_freeze(ROW)
        with mock.patch.object(fc, "policy_for", return_value=(fc.POLICIES / "airflow.yaml", "0" * 64, "DRAFT")):
            with self.assertRaises(SystemExit) as e:
                self.run_freeze(ROW)
        self.assertIn("changed since the freeze", str(e.exception))

    def test_refresh_freezes_a_new_version_deliberately(self):
        self.run_freeze(ROW)
        self.assertEqual(self.run_freeze(dict(ROW, head_sha="x" * 40), refresh=True), "frozen")
        self.assertEqual(len(list(self.out.glob("AF-01.invalid-*"))), 1)

    def test_row_without_pinned_shas_is_not_refused(self):
        self.run_freeze(ROW)
        self.assertEqual(self.run_freeze(dict(ROW, head_sha="", base_sha="")), "skipped")


if __name__ == "__main__":
    unittest.main()
