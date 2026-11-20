"""Tests for scripts/history.py: refs pinned from the merge commit (standard library only, no network).

    python -m unittest discover -s tests -v

Each test builds small Git repositories with the git CLI in a temporary folder. "origin" plays GitHub:
it holds refs/pull/<n>/head, and the clone fetches it from there.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import history


def run(cwd: Path, *args: str) -> str:
    env_args = ["-c", "user.name=Test", "-c", "user.email=test@example.test", "-c", "commit.gpgsign=false",
                "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false"]
    res = subprocess.run(["git", *env_args, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def commit(repo: Path, path: str, text: str, msg: str) -> str:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    run(repo, "add", path)
    run(repo, "commit", "-q", "-m", msg)
    return run(repo, "rev-parse", "HEAD")


class Fixture:
    """origin with main (a.py) and a PR branch (b.py, c.py); a clone of it in work/."""

    def __init__(self, tmp: str):
        self.origin = Path(tmp) / "origin"
        self.origin.mkdir()
        run(self.origin, "init", "-q")
        self.root = commit(self.origin, "a.py", "a = 1\n", "root")
        run(self.origin, "checkout", "-q", "-b", "pr")
        commit(self.origin, "b.py", "b = 1\n", "AIRFLOW-1 add b")
        self.head = commit(self.origin, "c.py", "c = 1\n", "AIRFLOW-1 add c")
        run(self.origin, "update-ref", "refs/pull/7/head", self.head)
        run(self.origin, "checkout", "-q", "main")
        self.main_moved = commit(self.origin, "a.py", "a = 2\n", "unrelated change on main")
        self.files = [{"filename": "b.py"}, {"filename": "c.py"}]

    def clone(self) -> Path:
        work = self.origin.parent / "work"
        run(self.origin.parent, "clone", "-q", str(self.origin), str(work))
        return work


class PinTests(unittest.TestCase):
    def test_two_parent_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from x/pr", "pr")
            merge = run(fx.origin, "rev-parse", "HEAD")
            work = fx.clone()
            got = history.pin(work, merge, 7, fx.files, api_base="api-base", api_head="api-head")
            self.assertEqual(got["merge_strategy"], "merge")
            self.assertEqual(got["base_at_merge"], fx.main_moved)
            self.assertEqual(got["head_at_merge"], fx.head)
            self.assertEqual(got["merge_base_sha"], fx.root)
            self.assertEqual(got["historical_diff_status"], "verified", got["historical_diff_reason"])
            self.assertEqual((got["api_base_sha"], got["api_head_sha"]), ("api-base", "api-head"))

    def test_single_parent_merge_uses_pr_head_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "AIRFLOW-1 add b and c (#7)")
            squash = run(fx.origin, "rev-parse", "HEAD")
            work = fx.clone()
            got = history.pin(work, squash, 7, fx.files)
            self.assertEqual(got["merge_strategy"], "single_parent")
            self.assertEqual(got["base_at_merge"], fx.main_moved)
            self.assertEqual(got["head_at_merge"], fx.head)  # fetched from origin's refs/pull/7/head
            self.assertEqual(got["merge_base_sha"], fx.root)
            self.assertEqual(got["historical_diff_status"], "verified", got["historical_diff_reason"])

    def test_file_list_mismatch_is_unverifiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "squash (#7)")
            squash = run(fx.origin, "rev-parse", "HEAD")
            work = fx.clone()
            got = history.pin(work, squash, 7, [{"filename": "b.py"}])  # API says one file, Git says two
            self.assertEqual(got["historical_diff_status"], "unverifiable")
            self.assertIn("1 extra (e.g. c.py)", got["historical_diff_reason"])

    def test_missing_pr_head_is_unverifiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "squash (#8)")
            squash = run(fx.origin, "rev-parse", "HEAD")
            got = history.pin(fx.clone(), squash, 8, fx.files)  # no refs/pull/8/head on origin
            self.assertEqual(got["historical_diff_status"], "unverifiable")
            self.assertIn("pull/8/head", got["historical_diff_reason"])

    def test_later_main_movement_does_not_change_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "pr")
            merge = run(fx.origin, "rev-parse", "HEAD")
            work = fx.clone()
            before = history.pin(work, merge, 7, fx.files)
            commit(fx.origin, "a.py", "a = 3\n", "main moves on after the merge")
            commit(fx.origin, "d.py", "d = 1\n", "and again")
            run(work, "fetch", "-q", "origin")
            run(work, "reset", "-q", "--hard", "origin/main")
            after = history.pin(work, merge, 7, fx.files)
            self.assertEqual(before, after)
            self.assertEqual(after["historical_diff_status"], "verified")

    def test_rename_counts_both_paths(self):
        self.assertEqual(history.pr_file_set([{"filename": "new.py", "previous_filename": "old.py"}, {"filename": "x.py"}]),
                         {"new.py", "old.py", "x.py"})

    def test_unreadable_merge_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = history.pin(Path(tmp), "0" * 40, 1, [])
            self.assertEqual(got["historical_diff_status"], "unverifiable")
            self.assertIn("merge commit not readable", got["historical_diff_reason"])


if __name__ == "__main__":
    unittest.main()
