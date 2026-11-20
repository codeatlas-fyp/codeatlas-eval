"""Tests for the Jira source preference (cached REST copy before the mail archive) in scripts/common.py and
scripts/jira_archive.py (standard library only, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common
import jira_archive as ja

CUTOFF = "2022-04-10T00:00:00Z"


def rest_issue(key="ARROW-1", edits=()):
    """A REST-shaped issue (no source field, as saved by older runs) with summary/description edits."""
    return {"key": key, "fields": {"summary": "now", "description": "current text"},
            "changelog": {"histories": [{"created": at, "items": [item]} for at, item in edits]}}


def archive_copy(key="ARROW-1"):
    return {"key": key, "source": ja.SOURCE, "archive": {"list": "issues@arrow.apache.org"},
            "fields": {"summary": "s", "description": ""}, "changelog": {"histories": []}}


class CacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def save(self, pr, issue, key="ARROW-1"):
        path = self.raw / "arrow" / str(pr) / f"jira_{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(issue), encoding="utf-8")

    def test_rest_copy_in_the_prs_folder_is_used(self):
        self.save(12, rest_issue())
        got = common.cached_rest_issue("arrow", "ARROW-1", 12, raw_root=self.raw)
        self.assertEqual(got["source"], "jira_rest_cache")
        self.assertEqual(got["cache_path"], "arrow/12/jira_ARROW-1.json")

    def test_rest_copy_of_another_pr_is_used(self):
        self.save(99, rest_issue())
        self.assertEqual(common.cached_rest_issue("arrow", "ARROW-1", 12, raw_root=self.raw)["source"],
                         "jira_rest_cache")

    def test_archive_copy_or_no_changelog_is_not_a_cache(self):
        self.save(12, archive_copy())
        self.save(13, {"key": "ARROW-1", "fields": {"summary": "s"}})   # REST shape, no changelog
        self.assertIsNone(common.cached_rest_issue("arrow", "ARROW-1", 12, raw_root=self.raw))
        self.assertIsNone(common.cached_rest_issue("arrow", "ARROW-2", raw_root=self.raw))

    def test_jira_issue_for_prefers_the_cache(self):
        ev = self.raw / "eval"
        path = ev / "pool" / "raw" / "arrow" / "12" / "jira_ARROW-1.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(rest_issue()), encoding="utf-8")
        cfg = {"name": "arrow", "jira_base": "https://jira.example.test"}
        with mock.patch.object(common, "EVAL", ev), \
                mock.patch.object(common, "jira_issue", side_effect=AssertionError("must not fetch")):
            got = common.jira_issue_for(cfg, "ARROW-1", 12)
        self.assertEqual(got["source"], "jira_rest_cache")
        self.assertEqual(got["fields"]["description"], "current text")

    def test_without_cache_the_archive_is_used(self):
        cfg = {"name": "arrow", "jira_base": "https://jira.example.test"}
        with mock.patch.object(common, "cached_rest_issue", return_value=None), \
                mock.patch.object(common, "jira_issue", return_value=archive_copy()) as fetch:
            self.assertEqual(common.jira_issue_for(cfg, "ARROW-1", 12)["source"], ja.SOURCE)
        fetch.assert_called_once_with("https://jira.example.test", "ARROW-1")


class CacheReconstructionTests(unittest.TestCase):
    def test_edits_after_the_cutoff_are_reversed(self):
        issue = rest_issue(edits=[
            ("2022-04-01T00:00:00.000+0000", {"field": "summary", "fromString": "first", "toString": "middle"}),
            ("2022-04-20T00:00:00.000+0000", {"field": "summary", "fromString": "middle", "toString": "now"}),
            ("2022-04-21T00:00:00.000+0000", {"field": "description", "fromString": "old text",
                                              "toString": "current text"})]) | {"source": "jira_rest_cache"}
        r = ja.reconstruct_at(issue, CUTOFF)
        self.assertEqual((r["source"], r["status"]), ("jira_rest_cache", "reconstructed"))
        self.assertEqual((r["summary"], r["description"]), ("middle", "old text"))
        self.assertIn("source: jira_rest_cache", ja.cutoff_file_text(issue, CUTOFF))

    def test_edit_without_old_value_is_unverifiable(self):
        issue = rest_issue(edits=[("2022-04-20T00:00:00.000+0000", {"field": "description", "toString": "x"})])
        r = ja.reconstruct_at(issue | {"source": "jira_rest_cache"}, CUTOFF)
        self.assertEqual(r["status"], "unverifiable")
        self.assertEqual((r["summary"], r["description"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
