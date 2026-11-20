"""Tests for archive issues whose list holds only the Created email (created_text_only) in scripts/jira_archive.py
and build_pool.requirement_edited (standard library only, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_pool as bp
import jira_archive as ja

CUTOFF = "2022-05-01T00:00:00Z"
CREATED = """Some One created ARROW-1:
-------------------------------

             Summary: Fix the reader
                 Key: ARROW-1
             Project: Apache Arrow
          Issue Type: Bug

The reader drops the last row.
"""
UPDATED_STATUS = """
     [ https://issues.apache.org/jira/browse/ARROW-1?page=x ]

Some One updated ARROW-1:
-------------------------
    Resolution: Fixed
"""


def email(kind, mid, epoch):
    return {"subject": f"[jira] [{kind}] (ARROW-1) Fix the reader", "mid": mid, "epoch": epoch}


class Fake:
    def __init__(self, emails, bodies):
        self.emails, self.bodies = emails, bodies

    def __call__(self, url):
        if "/stats.lua?" in url:
            return {"emails": self.emails if "list=issues" in url else []}
        if "/email.lua?" in url:
            return {"body": self.bodies[url.split("id=")[1]]}
        raise AssertionError(url)


class CreatedTextOnlyTests(unittest.TestCase):
    def test_only_a_created_email_gives_created_text_only(self):
        issue = ja.archive_issue("ARROW-1", Fake([email("Created", "c1", 1650000000)], {"c1": CREATED}), pause=0)
        self.assertEqual(issue["archive"]["email_kinds"], {"Created": 1})
        r = ja.reconstruct_at(issue, CUTOFF)
        self.assertEqual(r["status"], "created_text_only")
        self.assertEqual(r["note"], "edit history not available in the archive")
        self.assertEqual(r["summary"], "Fix the reader")
        text = ja.cutoff_file_text(issue, CUTOFF)
        self.assertIn("reconstruction_status: created_text_only", text)
        self.assertIn("The reader drops the last row.", text)   # the created text is still given

    def test_later_emails_keep_reconstructed(self):
        fake = Fake([email("Created", "c1", 1650000000), email("Updated", "u1", 1650100000),
                     email("Commented", "m1", 1650200000)], {"c1": CREATED, "u1": UPDATED_STATUS})
        issue = ja.archive_issue("ARROW-1", fake, pause=0)
        self.assertEqual(issue["archive"]["email_kinds"], {"Commented": 1, "Created": 1, "Updated": 1})
        self.assertEqual(ja.reconstruct_at(issue, CUTOFF)["status"], "reconstructed")

    def test_old_copy_without_email_kinds(self):
        old = {"key": "ARROW-1", "source": ja.SOURCE, "archive": {"list": "issues@arrow.apache.org"},
               "fields": {"summary": "s", "description": "d"}, "changelog": {"histories": []}}
        self.assertEqual(ja.reconstruct_at(old, CUTOFF)["status"], "created_text_only")   # unknown is not unchanged
        old["changelog"]["histories"] = [{"created": "2022-04-01T00:00:00.000+0000",
                                          "items": [{"field": "description", "toString": "d2"}]}]
        self.assertEqual(ja.reconstruct_at(old, CUTOFF)["status"], "reconstructed")

    def test_rest_copies_are_never_created_text_only(self):
        rest = {"key": "ARROW-1", "source": "jira_rest_cache", "fields": {"summary": "s", "description": ""},
                "changelog": {"histories": []}}
        self.assertEqual(ja.reconstruct_at(rest, CUTOFF)["status"], "reconstructed")

    def test_email_kinds_backfill(self):
        fake = Fake([email("Created", "c1", 1650000000), email("Created", "c1", 1650000000)], {})
        self.assertEqual(ja.archive_email_kinds("ARROW-1", fake), ("issues@arrow.apache.org", {"Created": 1}))
        self.assertIsNone(ja.archive_email_kinds("ARROW-1", Fake([], {})))


class RequirementEditedTests(unittest.TestCase):
    ONLY_CREATED = {"key": "ARROW-1", "source": ja.SOURCE, "archive": {"email_kinds": {"Created": 1}},
                    "fields": {"summary": "s", "description": "d"}, "changelog": {"histories": []}}
    EDITED = {"key": "ARROW-2", "source": "jira_rest_cache", "fields": {"summary": "s", "description": "d"},
              "changelog": {"histories": [{"created": "2022-04-15T00:00:00.000+0000",
                                           "items": [{"field": "description", "fromString": "a", "toString": "d"}]}]}}

    def edited(self, issues):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bp, "jira_issue_for", side_effect=lambda cfg, key, pr=None: issues[key]):
            return bp.requirement_edited({"name": "arrow"}, list(issues), "2022-04-10T00:00:00Z", CUTOFF, Path(tmp))

    def test_created_text_only_row_cannot_be_proven_unchanged(self):
        self.assertIsNone(self.edited({"ARROW-1": self.ONLY_CREATED}))

    def test_an_edit_on_another_key_still_counts(self):
        self.assertTrue(self.edited({"ARROW-1": self.ONLY_CREATED, "ARROW-2": self.EDITED}))


if __name__ == "__main__":
    unittest.main()
