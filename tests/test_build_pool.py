"""Tests for the merge rule and the raw cache in scripts/build_pool.py (standard library only).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_pool as bp

COMMIT = {"sha": "0123456789abcdef", "time": "2022-04-05T10:11:12+02:00", "subject": "ARROW-1: fix", "body": "Closes #12751"}


class MergeTimeTests(unittest.TestCase):
    def test_github_merge_keeps_githubs_time(self):
        self.assertEqual(bp.merge_time({"merged_at": "2019-10-01T11:40:43Z", "state": "closed"}, COMMIT),
                         ("2019-10-01T11:40:43Z", "github"))

    def test_script_merge_uses_commit_time_in_utc(self):
        """Arrow/Spark: PR closed with merged_at null, commit on main -> merged at the commit time."""
        merged_at, how = bp.merge_time({"merged_at": None, "state": "closed"}, COMMIT)
        self.assertEqual(merged_at, "2022-04-05T08:11:12Z")
        self.assertEqual(how, "script (commit 0123456789 on main)")

    def test_open_pr_is_not_merged(self):
        self.assertEqual(bp.merge_time({"merged_at": None, "state": "open"}, COMMIT), ("", ""))

    def test_merged_via_is_a_pool_column(self):
        self.assertEqual(bp.FIELDS[-1], "merged_via")


class CacheTests(unittest.TestCase):
    def test_reads_all_four_files_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            self.assertIsNone(bp.cached_pr(raw))
            for name, data in (("pr", {"number": 1}), ("files", []), ("reviews", []), ("commits", [{"sha": "a"}])):
                (raw / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(bp.cached_pr(raw), ({"number": 1}, [], [], [{"sha": "a"}]))
            (raw / "reviews.json").write_text("[{", encoding="utf-8")  # cut short by a crash
            self.assertIsNone(bp.cached_pr(raw))



class MainRunTests(unittest.TestCase):
    def test_recheck_turns_old_unmerged_row_into_script_merged_from_cache(self):
        from unittest import mock

        from common import read_csv, write_csv

        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp)
            pool = ev / "pool" / "arrow_pool.csv"
            old_fields = bp.FIELDS[:-1]  # a pool written before merged_via existed
            write_csv(pool, [{f: "" for f in old_fields} | {"pr_number": "12751", "included": "no",
                              "exclusion_reason": "not merged on GitHub (check script-merge)"}], old_fields)
            raw = ev / "pool" / "raw" / "arrow" / "12751"
            raw.mkdir(parents=True)
            pr = {"number": 12751, "state": "closed", "merged_at": None, "html_url": "u", "title": "ARROW-1: fix",
                  "user": {"login": "dev", "type": "User"}, "head": {"sha": "h", "ref": "b"}, "base": {"sha": "b0"},
                  "body": "", "created_at": "2022-04-01T00:00:00Z", "closed_at": "2022-04-05T08:11:20Z"}
            files = [{"filename": "python/pyarrow/a.py"}]
            reviews = [{"state": "APPROVED", "commit_id": "h", "user": {"login": "rev"}}]
            commits = [{"commit": {"message": "ARROW-1: fix", "committer": {"date": "2022-04-02T00:00:00Z"}}}]
            for name, data in (("pr", pr), ("files", files), ("reviews", reviews), ("commits", commits)):
                (raw / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
            cfg = {"name": "arrow", "github": "apache/arrow", "analysis_root": "python/", "key_regex": r"\bARROW-\d+\b",
                   "window": {"since": "2022-04-01", "until": "2022-06-30"}, "jira_base": "j"}
            with mock.patch.object(bp, "EVAL", ev), mock.patch.object(bp, "repo_cfg", return_value=cfg), \
                    mock.patch.object(bp, "ensure_clone", return_value=ev), \
                    mock.patch.object(bp, "first_parent_commits", return_value=[COMMIT | {"subject": "ARROW-1: fix"}]), \
                    mock.patch.object(bp, "merged_branch_messages", return_value=""), \
                    mock.patch.object(bp, "codeowners_at", return_value=(None, None)), \
                    mock.patch.object(bp, "gh", side_effect=AssertionError("cache should be used")), \
                    mock.patch("builtins.print"), \
                    mock.patch.object(sys, "argv", ["build_pool.py", "--repo", "arrow", "--recheck-unmerged"]):
                bp.main()
            (row,) = read_csv(pool)
            self.assertEqual(row["included"], "yes")
            self.assertEqual(row["merged_at"], "2022-04-05T08:11:12Z")
            self.assertEqual(row["merged_via"], "script (commit 0123456789 on main)")
            self.assertEqual(row["provisional_category"], "supported_approval")
            self.assertEqual(row["keys_found"], "ARROW-1")


if __name__ == "__main__":
    unittest.main()
