"""Tests for scripts/issue_summary.py (standard library only)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_pool
import issue_summary
from common import read_csv, write_csv


class IssueSummaryTests(unittest.TestCase):
    def test_counts_description_and_marks_title_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp)
            base = {f: "" for f in build_pool.FIELDS}
            write_csv(ev / "pool" / "airflow_pool.csv", [
                base | {"pr_number": "1", "keys_found": "AIRFLOW-1", "included": "yes", "provisional_category": "x"},
                base | {"pr_number": "2", "keys_found": "AIRFLOW-2", "included": "yes", "provisional_category": "y"},
                base | {"pr_number": "3", "keys_found": "AIRFLOW-3", "included": "no"},
                base | {"pr_number": "4", "keys_found": "AIRFLOW-4", "included": "yes"},  # not fetched yet
            ], build_pool.FIELDS)
            for n, desc in (("1", ""), ("2", "Line one.\n\n* criterion\n")):
                d = ev / "pool" / "raw" / "airflow" / n
                d.mkdir(parents=True)
                issue = {"fields": {"summary": f"S{n}", "description": desc},
                         "archive": {"list": "commits@airflow.apache.org"}}
                (d / f"jira_AIRFLOW-{n}.json").write_text(json.dumps(issue), encoding="utf-8")
            with mock.patch.object(issue_summary, "EVAL", ev), \
                    mock.patch.object(issue_summary, "repo_cfg", return_value={"name": "airflow"}), \
                    mock.patch("builtins.print") as printed:
                self.assertEqual(issue_summary.main(["--repo", "airflow"]), 0)
            got = read_csv(ev / "pool" / "airflow_issues.csv")
            self.assertEqual([(r["key"], r["title_only"], r["description_lines"]) for r in got],
                             [("AIRFLOW-1", "yes", "0"), ("AIRFLOW-2", "no", "2")])
            self.assertIn("1 keys have no saved issue yet", " ".join(str(c) for c in printed.call_args_list))


if __name__ == "__main__":
    unittest.main()
