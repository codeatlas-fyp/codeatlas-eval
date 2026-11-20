"""Tests for scripts/requirement_quality.py (B3; standard library only, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import requirement_quality as rq


def archive_issue(description, edits=()):
    return {"key": "AIRFLOW-1", "source": "apache_mail_archive", "archive": {},
            "fields": {"summary": "S", "description": description},
            "changelog": {"histories": [{"created": at, "items": [{"field": "description", "toString": text}]}
                                        for at, text in edits]}}


class ClassifyTextTests(unittest.TestCase):
    def test_no_description_is_title_only(self):
        self.assertEqual(rq.classify_text(""), "title_only")
        self.assertEqual(rq.classify_text("  \n "), "title_only")
        self.assertEqual(rq.classify_text(None), "title_only")

    def test_lists_are_explicit_criteria(self):
        for text in ("Steps:\n* add the hook\n* add tests", "Do:\n- one\n- two", "# first\n# second",
                     "1. parse\n2. store", "a) this\nb) that"):
            self.assertEqual(rq.classify_text(text), "explicit_criteria", text)

    def test_acceptance_criteria_words_are_explicit(self):
        self.assertEqual(rq.classify_text("Acceptance Criteria: the DAG reloads."), "explicit_criteria")

    def test_prose_is_descriptive(self):
        self.assertEqual(rq.classify_text("The scheduler crashes when a DAG has no tasks. It should skip it."),
                         "descriptive_issue")

    def test_heading_or_hyphenated_word_is_not_a_list(self):
        self.assertEqual(rq.classify_text("h3. Background\nThe hook is slow."), "descriptive_issue")
        self.assertEqual(rq.classify_text("-1 is returned for a non-existent pool."), "descriptive_issue")


class ClassifyIssueTests(unittest.TestCase):
    def test_missing_issue_is_unavailable(self):
        self.assertEqual(rq.classify_issue(None), "unavailable")

    def test_description_at_the_cutoff_is_used(self):
        issue = archive_issue("", edits=[("2019-10-05T00:00:00.000+0000", "* a\n* b")])
        self.assertEqual(rq.classify_issue(issue, "2019-10-01T00:00:00Z"), "title_only")   # list added later
        self.assertEqual(rq.classify_issue(issue, "2019-10-06T00:00:00Z"), "explicit_criteria")


class RowQualityTests(unittest.TestCase):
    Q = {"AIRFLOW-1": "title_only", "AIRFLOW-2": "explicit_criteria"}

    def test_best_among_verified_keys(self):
        q, note = rq.row_quality("AIRFLOW-1:commit;AIRFLOW-2:body", self.Q)
        self.assertEqual(q, "title_only")          # AIRFLOW-2 is only in the description: not verified
        self.assertIn("AIRFLOW-1", note)

    def test_no_verified_key_uses_all_keys_with_a_note(self):
        q, note = rq.row_quality("AIRFLOW-1:title;AIRFLOW-2:body", self.Q)
        self.assertEqual(q, "explicit_criteria")
        self.assertEqual(note, "no verified key: best among all keys")

    def test_unknown_key_is_unavailable_and_no_key_is_empty(self):
        self.assertEqual(rq.row_quality("AIRFLOW-9:commit", self.Q), ("unavailable", ""))
        self.assertEqual(rq.row_quality("", self.Q), ("", "no Jira key"))


if __name__ == "__main__":
    unittest.main()
