"""Tests for scripts/jira_archive.py (standard library only).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import jira_archive as ja

CREATED = """Tobiasz Kedzierski created AIRFLOW-5477:
-------------------------------------------

             Summary: Rewrite Google PubSub Hook to Google Cloud Python
                 Key: AIRFLOW-5477
                 URL: https://issues.apache.org/jira/browse/AIRFLOW-5477
             Project: Apache Airflow
          Issue Type: Improvement
          Components: gcp
    Affects Versions: 1.10.5
            Reporter: Tobiasz Kedzierski
            Assignee: Tobiasz Kedzierski


Rewrite the PubSub hook to use google-cloud-pubsub.
Acceptance criteria:
* the hook uses the new client
* operators keep their arguments



--
This message was sent by Atlassian Jira
(v8.3.2#803003)
"""

CREATED_LONG_SUMMARY = """Someone created AIRFLOW-9:
-------------------------

             Summary: A very long summary that Jira wraps onto the next line because it is
                      longer than the column: really
                 Key: AIRFLOW-9
          Issue Type: Bug


Body line.

--
This message was sent by Atlassian Jira
"""

UPDATED_DESCRIPTION = """
     [ https://issues.apache.org/jira/browse/AIRFLOW-5477?page=com.atlassian.jira.plugin.system.issuetabpanels:all-tabpanel ]

Kamil Bregula updated AIRFLOW-5477:
-----------------------------------
    Description: 
Rewrite the PubSub hook to use google-cloud-pubsub.
Acceptance criteria:
* the hook uses the new client
* operators keep their arguments
* add system tests

--
This message was sent by Atlassian Jira
(v8.3.2#803003)
"""

UPDATED_STATUS = """
     [ https://issues.apache.org/jira/browse/AIRFLOW-5477?page=... ]

Kaxil Naik updated AIRFLOW-5477:
--------------------------------
    Fix Version/s: 2.0.0
       Resolution: Fixed
           Status: Resolved  (was: Open)

--
This message was sent by Atlassian Jira
"""

UPDATED_SUMMARY = """Kamil updated AIRFLOW-5477:
---------------------------
    Summary: Rewrite PubSub hook  (was: Rewrite Google PubSub Hook to Google Cloud Python)
"""


def email(mid: str, subject: str, epoch: int, body: str = "...") -> dict:
    return {"mid": mid, "id": mid, "message-id": f"<{mid}@x>", "subject": subject, "epoch": epoch, "body": body[:20]}


class FakeArchive:
    """Answers stats.lua and email.lua the way lists.apache.org does; records the URLs asked for."""

    def __init__(self, by_list: dict[str, list[dict]], bodies: dict[str, str]):
        self.by_list, self.bodies, self.urls = by_list, bodies, []

    def __call__(self, url: str):
        self.urls.append(url)
        if "/stats.lua?" in url:
            lst = url.split("list=")[1].split("&")[0]
            return {"emails": self.by_list.get(lst, [])}
        if "/email.lua?" in url:
            return {"body": self.bodies[url.split("id=")[1]]}
        raise AssertionError(url)


class ParseTests(unittest.TestCase):
    def test_subject(self):
        self.assertEqual(ja.parse_subject("[jira] [Created] (AIRFLOW-5477) Rewrite Google PubSub Hook to\n Google Cloud Python"),
                         ("Created", "AIRFLOW-5477", "Rewrite Google PubSub Hook to Google Cloud Python"))
        self.assertIsNone(ja.parse_subject("[GitHub] [airflow] TobKed opened a new pull request #6096"))

    def test_created_fields_and_description(self):
        f = ja.parse_created(CREATED)
        self.assertEqual(f["Summary"], "Rewrite Google PubSub Hook to Google Cloud Python")
        self.assertEqual(f["Issue Type"], "Improvement")
        self.assertEqual(f["Components"], "gcp")
        self.assertTrue(f["Description"].startswith("Rewrite the PubSub hook"))
        self.assertTrue(f["Description"].endswith("* operators keep their arguments"))
        self.assertNotIn("Atlassian", f["Description"])

    def test_wrapped_summary_is_joined(self):
        f = ja.parse_created(CREATED_LONG_SUMMARY)
        self.assertEqual(f["Summary"], "A very long summary that Jira wraps onto the next line because it is "
                                       "longer than the column: really")
        self.assertEqual(f["Description"], "Body line.")

    def test_updated_description_and_summary(self):
        items = ja.parse_updated(UPDATED_DESCRIPTION)
        self.assertEqual([i["field"] for i in items], ["description"])
        self.assertTrue(items[0]["toString"].endswith("* add system tests"))
        self.assertEqual(ja.parse_updated(UPDATED_SUMMARY), [{"field": "summary", "toString": "Rewrite PubSub hook"}])
        self.assertEqual(ja.parse_updated(UPDATED_STATUS), [])

    def test_domain(self):
        self.assertEqual(ja.project_domain("SPARK-39000"), "spark.apache.org")


class ArchiveIssueTests(unittest.TestCase):
    def setUp(self):
        commits = [
            email("c1", "[jira] [Created] (AIRFLOW-5477) Rewrite Google PubSub Hook to\n Google Cloud Python", 1568382240),
            email("c1", "[jira] [Created] (AIRFLOW-5477) Rewrite Google PubSub Hook to Google Cloud Python", 1568382240),
            email("g1", "[GitHub] [airflow] TobKed opened a new pull request #6096: [AIRFLOW-5477] Rewrite", 1568382358),
            email("x1", "[jira] [Created] (AIRFLOW-54770) Another issue", 1568382000),
            email("u2", "[jira] [Updated] (AIRFLOW-5477) Rewrite Google PubSub Hook", 1568900000),
            email("u1", "[jira] [Updated] (AIRFLOW-5477) Rewrite Google PubSub Hook", 1568500000),
        ]
        self.fake = FakeArchive({"commits": commits}, {"c1": CREATED, "u1": UPDATED_DESCRIPTION, "u2": UPDATED_STATUS})

    def test_rebuilds_issue_in_jira_shape(self):
        issue = ja.archive_issue("AIRFLOW-5477", self.fake, pause=0)
        self.assertEqual(issue["fields"]["summary"], "Rewrite Google PubSub Hook to Google Cloud Python")
        self.assertEqual(issue["fields"]["created"], "2019-09-13T13:44:00.000+0000")
        self.assertEqual(issue["archive"]["list"], "commits@airflow.apache.org")
        self.assertEqual(len(issue["changelog"]["histories"]), 1)  # the status-only update has no tracked field
        self.assertEqual(issue["changelog"]["histories"][0]["items"][0]["field"], "description")
        self.assertIn("source", issue)
        # issues@ is searched first and is empty, so commits@ is used; the other key and GitHub mail are ignored
        self.assertIn("list=issues", self.fake.urls[0])
        self.assertFalse(any("id=x1" in u or "id=g1" in u for u in self.fake.urls))

    def test_text_at_cutoff_uses_only_earlier_edits(self):
        issue = ja.archive_issue("AIRFLOW-5477", self.fake, pause=0)
        before = ja.issue_text(issue, "2019-09-14T00:00:00Z")
        after = ja.issue_text(issue, "2019-09-20T00:00:00Z")
        self.assertNotIn("add system tests", before)
        self.assertIn("add system tests", after)
        self.assertTrue(before.startswith("Rewrite Google PubSub Hook to Google Cloud Python\n\n"))

    def test_missing_issue_raises(self):
        with self.assertRaises(ja.NotInArchive):
            ja.archive_issue("AIRFLOW-1", FakeArchive({}, {}), pause=0)

    def test_build_pool_flags_edit_inside_the_pr_window(self):
        """build_pool.requirement_edited reads the archive history: edit on 14 Sep 22:26 UTC."""
        import tempfile
        from unittest import mock

        import build_pool

        issue = ja.archive_issue("AIRFLOW-5477", self.fake, pause=0)
        cfg = {"jira_base": "https://issues.apache.org/jira"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_pool, "jira_issue", return_value=issue):
            raw = Path(tmp)
            self.assertTrue(build_pool.requirement_edited(cfg, ["AIRFLOW-5477"], "2019-09-13T14:00:00Z",
                                                          "2019-09-20T00:00:00Z", raw))
            self.assertFalse(build_pool.requirement_edited(cfg, ["AIRFLOW-5477"], "2019-09-15T00:00:00Z",
                                                           "2019-09-20T00:00:00Z", raw))
            self.assertTrue((raw / "jira_AIRFLOW-5477.json").exists())



class JiraFallbackTests(unittest.TestCase):
    def test_login_required_switches_to_archive_once(self):
        import io
        import urllib.error
        from unittest import mock

        import common

        common._JIRA_LOGIN_REQUIRED.clear()
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))
        with mock.patch.object(common, "_get", side_effect=err) as get, \
                mock.patch.object(ja, "archive_issue", return_value={"key": "AIRFLOW-1"}) as arch, \
                mock.patch("builtins.print"):
            self.assertEqual(common.jira_issue("https://issues.apache.org/jira", "AIRFLOW-1"), {"key": "AIRFLOW-1"})
            common.jira_issue("https://issues.apache.org/jira", "AIRFLOW-2")
        self.assertEqual(get.call_count, 1)  # Jira is not asked again after the first 401
        self.assertEqual(arch.call_count, 2)
        common._JIRA_LOGIN_REQUIRED.clear()


class FlagRequirementChangesTests(unittest.TestCase):
    def test_marks_edited_rows_and_skips_them_next_time(self):
        import json
        import tempfile
        from unittest import mock

        import build_pool
        import flag_requirement_changes as frc
        from common import read_csv, write_csv

        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp)
            pool = ev / "pool" / "airflow_pool.csv"
            base = {f: "" for f in build_pool.FIELDS}
            rows = [
                base | {"repo": "airflow", "pr_number": "6096", "keys_found": "AIRFLOW-5477", "included": "yes",
                        "merged_at": "2019-09-20T00:00:00Z", "provisional_category": "supported_approval"},
                base | {"repo": "airflow", "pr_number": "6097", "keys_found": "", "included": "yes",
                        "merged_at": "2019-09-20T00:00:00Z", "provisional_category": "no_key"},
            ]
            write_csv(pool, rows, build_pool.FIELDS)
            raw = ev / "pool" / "raw" / "airflow" / "6096"
            raw.mkdir(parents=True)
            (raw / "commits.json").write_text(json.dumps([{"commit": {"committer": {"date": "2019-09-13T14:00:00Z"}}}]))
            cfg = {"name": "airflow", "jira_base": "https://issues.apache.org/jira"}
            with mock.patch.object(frc, "EVAL", ev), mock.patch.object(frc, "repo_cfg", return_value=cfg), \
                    mock.patch.object(frc, "requirement_edited", return_value=True) as edited, \
                    mock.patch("builtins.print"):
                self.assertEqual(frc.main(["--repo", "airflow"]), 0)
                self.assertEqual(frc.main(["--repo", "airflow"]), 0)
            self.assertEqual(edited.call_count, 1)  # second run skips the checked row
            got = {r["pr_number"]: r["provisional_category"] for r in read_csv(pool)}
            self.assertEqual(got, {"6096": "requirement_changed", "6097": "no_key"})


if __name__ == "__main__":
    unittest.main()
