"""Jira status, priority, assignee and resolution at the cutoff (frozen-case evidence contract, 21 Nov 2026).

Standard library only, synthetic issues in the REST shape. python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import jira_archive as ja

CUTOFF = "2022-05-10T12:00:00Z"


def change(at, field, frm, frm_id, to, author="alice"):
    return {"created": at, "author": {"key": author}, "items": [
        {"field": field, "fromString": frm, "from": frm_id, "toString": to}]}


def rest_issue(histories, total=None, **fields):
    base = {"status": {"name": "Resolved", "id": "5", "statusCategory": {"name": "Done"}},
            "priority": {"name": "Major", "id": "3"},
            "assignee": {"key": "bob", "displayName": "Bob"},
            "resolution": {"name": "Fixed", "id": "1"},
            "created": "2022-05-01T09:00:00.000+0000", "summary": "s", "description": "d"}
    base.update(fields)
    cl = {"histories": histories}
    if total is not None:
        cl["total"] = total
    return {"key": "SPARK-1", "source": ja.CACHE_SOURCE, "fields": base, "changelog": cl}


HIST = [
    change("2022-05-02T10:00:00.000+0000", "status", "Open", "1", "In Progress"),
    change("2022-05-03T10:00:00.000+0000", "assignee", None, None, "Bob"),
    change("2022-05-20T10:00:00.000+0000", "status", "In Progress", "3", "Resolved", author="carol"),
    change("2022-05-20T10:00:00.000+0000", "resolution", None, None, "Fixed", author="carol"),
    change("2022-05-21T10:00:00.000+0000", "priority", "Minor", "4", "Major", author="dave"),
]


class StateAtCutoffTests(unittest.TestCase):
    def test_later_changes_are_undone(self):
        st = ja.state_at(rest_issue(HIST), CUTOFF)
        f = st["fields"]
        self.assertEqual(f["status"]["value"], "In Progress")
        self.assertEqual(f["status"]["value_id"], "3")
        self.assertEqual(f["priority"]["value"], "Minor")
        self.assertEqual(f["resolution"]["value"], None)        # unresolved at the cutoff
        self.assertEqual(f["resolution"]["reconstruction"], "reconstructed")
        self.assertEqual(f["assignee"]["value"], "Bob")          # assigned before the cutoff, unchanged since
        self.assertEqual(ja.state_summary(st), "reconstructed")
        self.assertIsNone(st["changelog_complete"])          # no total recorded: unknown
        self.assertTrue(ja.state_at(rest_issue(HIST, total=len(HIST)), CUTOFF)["changelog_complete"])

    def test_changes_up_to_cutoff_keep_time_and_author(self):
        st = ja.state_at(rest_issue(HIST), CUTOFF)
        self.assertEqual(st["fields"]["status"]["changes_up_to_cutoff"],
                         [{"at": "2022-05-02T10:00:00.000+0000", "author": "alice", "from": "Open", "to": "In Progress"}])
        self.assertEqual(st["fields"]["priority"]["changes_up_to_cutoff"], [])

    def test_fetched_state_never_leaks(self):
        st = ja.state_at(rest_issue(HIST), CUTOFF)
        self.assertNotEqual(st["fields"]["status"]["value"], "Resolved")
        self.assertIsNone(st["status_category"]["value"])
        self.assertEqual(st["status_category"]["reconstruction"], "unavailable")
        self.assertIn("NOT the state at the cutoff", st["note"])

    def test_truncated_changelog_is_unverifiable(self):
        st = ja.state_at(rest_issue(HIST, total=250), CUTOFF)
        self.assertFalse(st["changelog_complete"])
        for f in st["fields"].values():
            self.assertEqual((f["reconstruction"], f["value"]), ("unverifiable", None))
        self.assertEqual(ja.state_summary(st), "unavailable")

    def test_status_change_without_old_value_is_unverifiable(self):
        hist = HIST + [change("2022-05-22T10:00:00.000+0000", "status", None, None, "Closed")]
        st = ja.state_at(rest_issue(hist), CUTOFF)
        self.assertEqual((st["fields"]["status"]["reconstruction"], st["fields"]["status"]["value"]),
                         ("unverifiable", None))
        self.assertEqual(st["fields"]["priority"]["reconstruction"], "reconstructed")
        self.assertEqual(ja.state_summary(st), "partial")

    def test_mail_archive_gives_no_state(self):
        issue = {"key": "AIRFLOW-1", "source": ja.SOURCE, "fields": {"summary": "s", "status": {"name": "Closed"}},
                 "changelog": {"histories": []}}
        st = ja.state_at(issue, CUTOFF)
        for f in st["fields"].values():
            self.assertEqual((f["reconstruction"], f["value"]), ("unavailable", None))
        self.assertIn("carries no history", st["fields"]["status"]["note"])

    def test_inaccessible_issue_gives_no_state(self):
        st = ja.state_at({"key": "ARROW-9", "source": "none"}, CUTOFF)
        self.assertEqual(ja.state_summary(st), "unavailable")

    def test_issue_created_after_cutoff(self):
        st = ja.state_at(rest_issue(HIST, created="2022-06-01T00:00:00.000+0000"), CUTOFF)
        self.assertIn("after the cutoff", st["fields"]["status"]["note"])
        self.assertIsNone(st["fields"]["status"]["value"])

    def test_change_exactly_at_cutoff_counts_as_before(self):
        hist = [change("2022-05-10T12:00:00.000+0000", "status", "Open", "1", "Patch Available")]
        st = ja.state_at(rest_issue(hist, status={"name": "Patch Available", "id": "10002"}), CUTOFF)
        self.assertEqual(st["fields"]["status"]["value"], "Patch Available")


if __name__ == "__main__":
    unittest.main()
