"""Tests for the source-aware issue text at the cutoff (jira_archive.reconstruct_at, cutoff_file_text).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import jira_archive as ja

CUTOFF = "2019-10-01T12:00:00Z"


def archive_issue() -> dict:
    return {"key": "AIRFLOW-1", "source": ja.SOURCE, "archive": {"list": "commits@airflow.apache.org"},
            "fields": {"summary": "Original title", "description": "Original text."},
            "changelog": {"histories": [
                {"created": "2019-09-30T10:00:00.000+0000", "items": [{"field": "description", "toString": "Before cutoff."}]},
                {"created": "2019-10-02T10:00:00.000+0000", "items": [{"field": "summary", "toString": "Renamed later"},
                                                                       {"field": "description", "toString": "After cutoff."}]},
            ]}}


def rest_issue(with_old_value: bool = True) -> dict:
    later = {"field": "description", "toString": "Edited after the merge."}
    if with_old_value:
        later["fromString"] = "Text at the merge."
    return {"key": "SPARK-1", "source": ja.REST_SOURCE,
            "fields": {"summary": "Current title", "description": "Edited after the merge."},
            "changelog": {"histories": [
                {"created": "2019-09-01T00:00:00.000+0000",
                 "items": [{"field": "summary", "fromString": "First title", "toString": "Title at the merge"}]},
                {"created": "2019-10-05T00:00:00.000+0000",
                 "items": [{"field": "summary", "fromString": "Title at the merge", "toString": "Current title"}]},
                {"created": "2019-10-03T00:00:00.000+0000", "items": [later]},
                {"created": "2019-10-04T00:00:00.000+0000", "items": [{"field": "status", "toString": "Resolved"}]},
            ]}}


class ReconstructTests(unittest.TestCase):
    def test_archive_edit_after_cutoff_is_ignored(self):
        r = ja.reconstruct_at(archive_issue(), CUTOFF)
        self.assertEqual((r["source"], r["status"]), ("apache_mail_archive", "reconstructed"))
        self.assertEqual((r["summary"], r["description"]), ("Original title", "Before cutoff."))
        self.assertIn("1 later edit(s) ignored", r["note"])

    def test_rest_edit_after_cutoff_is_reversed_newest_first(self):
        r = ja.reconstruct_at(rest_issue(), CUTOFF)
        self.assertEqual((r["source"], r["status"]), ("jira_rest", "reconstructed"))
        self.assertEqual(r["summary"], "Title at the merge")       # not "First title": that edit was before the cutoff
        self.assertEqual(r["description"], "Text at the merge.")

    def test_rest_edit_without_old_value_is_unverifiable(self):
        r = ja.reconstruct_at(rest_issue(with_old_value=False), CUTOFF)
        self.assertEqual(r["status"], "unverifiable")
        self.assertIn("fromString", r["note"])
        self.assertEqual((r["summary"], r["description"]), ("", ""))  # nothing guessed

    def test_rest_edit_before_cutoff_without_old_value_does_not_matter(self):
        issue = rest_issue()
        issue["changelog"]["histories"][0]["items"][0].pop("fromString")
        self.assertEqual(ja.reconstruct_at(issue, CUTOFF)["status"], "reconstructed")

    def test_old_saved_archive_issue_is_recognised(self):
        issue = archive_issue()
        issue["source"] = "lists.apache.org archive of Jira notification emails"  # written before this fix
        self.assertEqual(ja.issue_source(issue), "apache_mail_archive")


class CutoffFileTests(unittest.TestCase):
    def test_header_then_text(self):
        text = ja.cutoff_file_text(archive_issue(), CUTOFF)
        header, body = text.split("---\n", 1)
        self.assertIn("source: apache_mail_archive\n", header)
        self.assertIn(f"cutoff: {CUTOFF}\n", header)
        self.assertIn("reconstruction_status: reconstructed\n", header)
        self.assertEqual(body, "Original title\n\nBefore cutoff.\n")

    def test_unverifiable_file_has_no_text(self):
        text = ja.cutoff_file_text(rest_issue(with_old_value=False), CUTOFF)
        self.assertIn("reconstruction_status: unverifiable\n", text)
        self.assertTrue(text.endswith("---\n"))

    def test_rest_answer_is_tagged_jira_rest(self):
        from unittest import mock

        import common

        common._JIRA_LOGIN_REQUIRED.clear()
        with mock.patch.object(common, "_get", return_value=({"key": "SPARK-1", "fields": {}}, {})):
            self.assertEqual(common.jira_issue("https://jira.example.test", "SPARK-1")["source"], "jira_rest")


if __name__ == "__main__":
    unittest.main()
