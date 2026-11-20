"""Tests for the Jira link status (A5): scripts/links.py and freeze_case.key_sources (standard library only).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import freeze_case as fc
import links
import update_pool as up

KEY_RE = r"\bAIRFLOW-\d+\b"
MERGED = "2019-10-01T12:00:00Z"


def renamed(at, old, new):
    return {"event": "renamed", "created_at": at, "rename": {"from": old, "to": new}}


def status_of(entries, key):
    (e,) = [x for x in entries if x["key"] == key]
    return e


class PoolStatusTests(unittest.TestCase):
    def test_pool_statuses_from_locations(self):
        self.assertEqual(links.pool_link_status("AIRFLOW-1:commit+title"), "verified")
        self.assertEqual(links.pool_link_status("AIRFLOW-1:branch"), "verified")
        self.assertEqual(links.pool_link_status("AIRFLOW-1:title"), "title_unchecked")
        self.assertEqual(links.pool_link_status("AIRFLOW-1:body"), "uncertain")
        self.assertEqual(links.pool_link_status(""), "")

    def test_row_takes_the_best_key(self):
        self.assertEqual(links.pool_link_status("AIRFLOW-1:body;AIRFLOW-2:title"), "title_unchecked")
        self.assertEqual(links.pool_link_status("AIRFLOW-1:body;AIRFLOW-2:commit"), "verified")


class TitleAtMergeTests(unittest.TestCase):
    def test_renames_after_the_cutoff_are_undone(self):
        tl = [renamed("2019-09-30T10:00:00Z", "WIP", "AIRFLOW-1 fix"),
              renamed("2019-10-02T10:00:00Z", "AIRFLOW-1 fix", "AIRFLOW-1 AIRFLOW-2 fix"),
              renamed("2019-10-03T10:00:00Z", "AIRFLOW-1 AIRFLOW-2 fix", "AIRFLOW-2 fix")]
        self.assertEqual(links.title_at("AIRFLOW-2 fix", tl, MERGED), "AIRFLOW-1 fix")

    def test_no_renames_keeps_the_title(self):
        self.assertEqual(links.title_at("AIRFLOW-1 fix", [{"event": "commented"}], MERGED), "AIRFLOW-1 fix")


class FreezeStatusTests(unittest.TestCase):
    def test_title_renamed_after_merge_makes_new_key_uncertain(self):
        tl = [renamed("2019-10-02T10:00:00Z", "AIRFLOW-1 fix", "AIRFLOW-2 fix")]
        merged_title = links.title_at("AIRFLOW-2 fix", tl, MERGED)
        got = links.freeze_link_statuses({"AIRFLOW-2": {"title"}}, merged_title, KEY_RE)
        self.assertEqual(status_of(got, "AIRFLOW-2")["status"], "uncertain")
        old = status_of(got, "AIRFLOW-1")        # the key the title had at the merge is kept
        self.assertEqual(old["status"], "verified")
        self.assertEqual(old["found_in"], ["title_at_merge"])

    def test_key_in_a_commit_is_verified(self):
        got = links.freeze_link_statuses({"AIRFLOW-3": {"commit", "body"}}, "no key here", KEY_RE)
        self.assertEqual(status_of(got, "AIRFLOW-3")["status"], "verified")

    def test_title_in_force_at_merge_is_verified(self):
        got = links.freeze_link_statuses({"AIRFLOW-4": {"title"}}, "[AIRFLOW-4] fix", KEY_RE)
        self.assertEqual(status_of(got, "AIRFLOW-4")["status"], "verified")

    def test_description_only_is_uncertain(self):
        got = links.freeze_link_statuses({"AIRFLOW-5": {"body"}}, "fix", KEY_RE)
        self.assertEqual(status_of(got, "AIRFLOW-5")["status"], "uncertain")

    def test_unreadable_timeline_leaves_title_keys_uncertain(self):
        got = links.freeze_link_statuses({"AIRFLOW-6": {"title"}}, None, KEY_RE)
        self.assertEqual(status_of(got, "AIRFLOW-6")["status"], "uncertain")


class KeySourcesTests(unittest.TestCase):
    def test_key_in_the_merge_commit_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git = ["git", "-c", "user.name=T", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
            (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
            subprocess.run([*git, "add", "a.py"], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-q", "-m", "[AIRFLOW-7] squashed (#9)"], cwd=repo, check=True)
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
            pr = {"title": "fix", "head": {"ref": "AIRFLOW-8-branch"}, "body": "see AIRFLOW-9"}
            commits = [{"commit": {"message": "wip"}}]
            where = fc.key_sources(repo, {"key_regex": KEY_RE}, pr, commits, sha)
        self.assertEqual(where, {"AIRFLOW-7": {"merge_commit"}, "AIRFLOW-8": {"branch"}, "AIRFLOW-9": {"body"}})
        got = links.freeze_link_statuses(where, "fix", KEY_RE)
        self.assertEqual([x["status"] for x in got], ["verified", "verified", "uncertain"])


class PoolMergeCommitTests(unittest.TestCase):
    def test_key_in_the_merge_commit_subject_makes_the_pool_row_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git = ["git", "-c", "user.name=T", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
            (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
            subprocess.run([*git, "add", "a.py"], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-q", "-m", "[AIRFLOW-1] fix (#9)\n\nmentions AIRFLOW-2"], cwd=repo, check=True)
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
            row = {"merge_commit_sha": sha, "key_locations": "AIRFLOW-1:title"}
            got = up.merge_commit_locations(repo, row, KEY_RE)
        self.assertEqual(got, "AIRFLOW-1:merge_commit+title")    # AIRFLOW-2 was not a key of the row: not added
        self.assertEqual(links.pool_link_status(got), "verified")


if __name__ == "__main__":
    unittest.main()
