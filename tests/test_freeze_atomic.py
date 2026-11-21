"""Tests for the atomic freeze and manifest in scripts/freeze_case.py (standard library only, no network).

    python -m unittest discover -s tests -v

collect() (which reads GitHub, Jira and the clone) is replaced by a fake that writes the evidence files, so
these tests check only staging, the manifest, --verify, skipping and the annotator files.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import freeze_case as fc

ROW = {"case_id": "AF-01", "set": "pilot", "repo": "airflow", "pr_number": "6216", "jira_keys": "AIRFLOW-1",
       "category_provisional": "supported_approval", "decision_cutoff_utc": "2019-10-01T11:40:43Z"}


def fake_collect(row, case_dir):
    src = case_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)
    for rel in fc.MANDATORY:
        (case_dir / rel).write_text(f"{rel} of {row['case_id']}\n", encoding="utf-8")
    (src / "jira_AIRFLOW-1.json").write_text("{}\n", encoding="utf-8")
    return {"mandatory": ["sources/jira_AIRFLOW-1.json"], "refs": {"merge_commit_sha": "abc"}}


def crashing_collect(row, case_dir):
    (case_dir / "sources").mkdir(parents=True, exist_ok=True)
    (case_dir / "sources" / "pr.json").write_text("{}\n", encoding="utf-8")
    raise ConnectionError("network dropped half-way")


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class AtomicFreezeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.final = self.out / "AF-01"

    def tearDown(self):
        self._tmp.cleanup()

    def freeze(self, collect=fake_collect, **kwargs):
        kwargs.setdefault("allow_draft", True)  # the repo's policy is still DRAFT: an engineering freeze
        with mock.patch.object(fc, "collect", side_effect=collect) as m:
            result, _ = quiet(fc.freeze, dict(ROW), self.out, **kwargs)
        return result, m

    def test_complete_freeze_has_manifest_and_verifies(self):
        self.assertEqual(self.freeze()[0], "frozen")
        manifest = json.loads((self.final / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["freeze_status"], "complete")
        self.assertEqual(manifest["freeze_tool_version"], fc.FREEZE_TOOL_VERSION)
        self.assertIn("sources/jira_AIRFLOW-1.json", manifest["mandatory_files"])
        self.assertIn("case.yaml", manifest["files"])
        for name in fc.ANNOTATOR_FILES:
            self.assertNotIn(name, manifest["files"])
        self.assertEqual(fc.verify_case(self.final), [])
        self.assertFalse((self.out / "AF-01.staging").exists())

    def test_interrupted_freeze_leaves_no_final_folder(self):
        with self.assertRaises(ConnectionError):
            self.freeze(crashing_collect)
        self.assertFalse(self.final.exists())
        self.assertTrue((self.out / "AF-01.staging").exists())
        self.assertEqual(self.freeze()[0], "frozen")   # the next run discards the staging folder
        self.assertEqual(fc.verify_case(self.final), [])
        self.assertFalse((self.out / "AF-01.staging").exists())

    def test_tampered_file_detected_by_verify(self):
        self.freeze()
        (self.final / "sources" / "reviews.json").write_text("[]\n", encoding="utf-8")
        code, out = quiet(fc.main, ["--verify", "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("AF-01: INVALID", out)
        self.assertIn("checksum mismatch: sources/reviews.json", out)
        code, out = quiet(fc.main, ["--verify", "--case", "AF-01", "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("checksum mismatch", out)

    def test_missing_and_extra_files_detected(self):
        self.freeze()
        (self.final / "sources" / "fetched_at.txt").unlink()
        (self.final / "sources" / "late.json").write_text("{}\n", encoding="utf-8")
        reasons = fc.verify_case(self.final)
        self.assertIn("mandatory file missing: sources/fetched_at.txt", reasons)
        self.assertIn("file not in manifest: sources/late.json", reasons)

    def test_rerun_of_complete_case_skips(self):
        self.freeze()
        result, m = self.freeze()
        self.assertEqual(result, "skipped")
        m.assert_not_called()

    def test_sources_without_manifest_is_not_done(self):
        (self.final / "sources").mkdir(parents=True)
        (self.final / "sources" / "pr.json").write_text("{}\n", encoding="utf-8")
        (self.final / "label_A.yaml").write_text("labeller: SM\n", encoding="utf-8")
        result, m = self.freeze()
        self.assertEqual(result, "frozen")
        m.assert_called_once()
        invalid = list(self.out.glob("AF-01.invalid-*"))
        self.assertEqual(len(invalid), 1)
        self.assertIn("no manifest.json", (invalid[0] / "REASON.txt").read_text(encoding="utf-8"))
        self.assertEqual((self.final / "label_A.yaml").read_text(encoding="utf-8"), "labeller: SM\n")

    def test_label_files_untouched_by_refreeze(self):
        self.freeze()
        texts = {name: f"# written by an annotator: {name}\n" for name in fc.ANNOTATOR_FILES}
        for name, text in texts.items():
            (self.final / name).write_text(text, encoding="utf-8")
        self.assertEqual(fc.verify_case(self.final), [])   # annotator edits do not invalidate the freeze
        (self.final / "sources" / "pr.json").write_text("tampered\n", encoding="utf-8")
        self.assertEqual(self.freeze()[0], "frozen")
        for name, text in texts.items():
            self.assertEqual((self.final / name).read_text(encoding="utf-8"), text)
        self.assertEqual(fc.verify_case(self.final), [])

    def test_labels_survive_a_refreeze_that_crashed(self):
        self.freeze()
        (self.final / "label_B.yaml").write_text("labeller: YU\n", encoding="utf-8")
        (self.final / "sources" / "pr.json").write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(ConnectionError):
            self.freeze(crashing_collect)            # old folder already moved to .invalid-*
        self.assertFalse(self.final.exists())
        self.freeze()
        self.assertEqual((self.final / "label_B.yaml").read_text(encoding="utf-8"), "labeller: YU\n")

    def test_cases_and_out_options(self):
        cases = self.out / "cases.csv"
        cases.write_text(",".join(ROW) + "\n" + ",".join(ROW.values()) + "\n", encoding="utf-8")
        frozen = self.out / "frozen"
        with mock.patch.object(fc, "collect", side_effect=fake_collect):
            code, _ = quiet(fc.main, ["--case", "AF-01", "--cases", str(cases), "--out", str(frozen), "--allow-draft"])
        self.assertEqual(code, 0)
        self.assertTrue((frozen / "AF-01" / "manifest.json").exists())
        code, out = quiet(fc.main, ["--verify", "--out", str(frozen)])
        self.assertEqual(code, 0)
        self.assertIn("AF-01: OK", out)


if __name__ == "__main__":
    unittest.main()
