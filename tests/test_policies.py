"""Tests for the baseline policy (B5): eval/policies/ and the policy check in scripts/freeze_case.py.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import freeze_case as fc

POLICIES = Path(__file__).resolve().parent.parent / "eval" / "policies"
HEADER = ("# Baseline policy v0.1 (20 Nov 2026) - identical for all repos - status: DRAFT until signed off by "
          "Areej, Yusra, Saleha")


class PolicyFilesTests(unittest.TestCase):
    def test_repo_files_equal_the_baseline(self):
        baseline = (POLICIES / "baseline.yaml").read_bytes()
        for repo in ("airflow", "arrow", "spark"):
            self.assertEqual((POLICIES / f"{repo}.yaml").read_bytes(), baseline, repo)

    def test_header_line(self):
        self.assertEqual((POLICIES / "baseline.yaml").read_text(encoding="utf-8").splitlines()[0], HEADER)

    def test_only_codeatlas_schema_fields(self):
        top = {line.split(":", 1)[0] for line in (POLICIES / "baseline.yaml").read_text(encoding="utf-8").splitlines()
               if line and not line.startswith((" ", "#"))}
        self.assertEqual(top, {"version", "workitem_key_pattern", "requirement_fields", "governance_paths", "approval",
                               "priority_authority", "cases", "semantic"})


class FreezePolicyTests(unittest.TestCase):
    ROW = {"case_id": "AF-01", "set": "pilot", "repo": "airflow", "pr_number": "1", "jira_keys": ""}

    def test_missing_policy_is_a_clear_error_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, empty = Path(tmp) / "out", Path(tmp) / "no-policies"
            empty.mkdir()
            with mock.patch.object(fc, "POLICIES", empty), \
                    mock.patch.object(fc, "collect", side_effect=AssertionError("must not collect")):
                with self.assertRaises(SystemExit) as ctx:
                    fc.freeze(dict(self.ROW), out)
            self.assertIn("airflow.yaml is missing", str(ctx.exception))
            self.assertIn("refusing to freeze", str(ctx.exception))
            self.assertFalse(out.exists())

    def test_policy_hash_and_status(self):
        path, digest, status = fc.policy_for("airflow")
        self.assertEqual(path.name, "airflow.yaml")
        self.assertEqual(digest, fc.sha256_file(POLICIES / "baseline.yaml"))
        self.assertTrue(status.startswith("Baseline policy v0.1"))
        self.assertIn("status: DRAFT", status)


if __name__ == "__main__":
    unittest.main()
