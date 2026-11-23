"""Content-level history check (audit 21 Nov, point 2): the PR's change vs the change that reached main.

    python -m unittest discover -s tests -v

Standard library only, no network: small Git repositories built with the git CLI in a temporary folder.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import history
from test_history import Fixture, commit, run


class ContentTests(unittest.TestCase):
    def test_squash_of_the_same_change_is_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "AIRFLOW-1 squash (#7)")
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, fx.files)
            self.assertEqual(got["historical_diff_status"], "verified")
            self.assertEqual(got["historical_content_status"], "identical", got["historical_content_reason"])

    def test_two_parent_merge_is_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--no-ff", "-m", "Merge pull request #7", "pr")
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, fx.files)
            self.assertEqual(got["historical_content_status"], "identical", got["historical_content_reason"])

    def test_merge_script_that_edits_the_change_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            (fx.origin / "c.py").write_text("c = 2  # edited while merging\n", encoding="utf-8")
            run(fx.origin, "add", "c.py")
            run(fx.origin, "commit", "-q", "-m", "squash with an edit (#7)")
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, fx.files)
            self.assertEqual(got["historical_diff_status"], "verified")  # same file list ...
            self.assertEqual(got["historical_content_status"], "differs")  # ... different content
            self.assertIn("1 of 2 files", got["historical_content_reason"])
            self.assertIn("c.py", got["historical_content_reason"])

    def test_evil_merge_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--no-ff", "--no-commit", "pr")
            (fx.origin / "b.py").write_text("b = 99\n", encoding="utf-8")
            run(fx.origin, "add", "b.py")
            run(fx.origin, "commit", "-q", "-m", "Merge pull request #7 (changed during the merge)")
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, fx.files)
            self.assertEqual(got["historical_content_status"], "differs")
            self.assertIn("b.py", got["historical_content_reason"])

    def test_base_moving_nearby_lines_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            origin.mkdir()
            run(origin, "init", "-q")
            commit(origin, "m.py", "x = 1\n\n\n\ny = 1\n", "root")
            run(origin, "checkout", "-q", "-b", "pr")
            head = commit(origin, "m.py", "x = 1\n\n\n\ny = 2\n", "AIRFLOW-2 change y")
            run(origin, "update-ref", "refs/pull/9/head", head)
            run(origin, "checkout", "-q", "main")
            commit(origin, "m.py", "x = 5\n\n\n\ny = 1\n", "unrelated change to x on main")
            run(origin, "merge", "-q", "--squash", "pr")
            run(origin, "commit", "-q", "-m", "AIRFLOW-2 change y (#9)")
            work = Path(tmp) / "work"
            run(Path(tmp), "clone", "-q", str(origin), str(work))
            got = history.pin(work, run(origin, "rev-parse", "HEAD"), 9, [{"filename": "m.py"}])
            self.assertEqual(got["historical_content_status"], "identical", got["historical_content_reason"])

    def test_unverified_file_list_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "squash (#7)")
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, [{"filename": "b.py"}])
            self.assertEqual(got["historical_diff_status"], "unverifiable")
            self.assertEqual(got["historical_content_status"], "not_checked")

    def test_binary_files_compare_by_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            run(fx.origin, "checkout", "-q", "pr")
            (fx.origin / "img.bin").write_bytes(bytes(range(256)))
            run(fx.origin, "add", "img.bin")
            run(fx.origin, "commit", "-q", "-m", "add binary")
            head = run(fx.origin, "rev-parse", "HEAD")
            run(fx.origin, "update-ref", "refs/pull/7/head", head)
            run(fx.origin, "checkout", "-q", "main")
            run(fx.origin, "merge", "-q", "--squash", "pr")
            run(fx.origin, "commit", "-q", "-m", "squash (#7)")
            files = [*fx.files, {"filename": "img.bin"}]
            got = history.pin(fx.clone(), run(fx.origin, "rev-parse", "HEAD"), 7, files)
            self.assertEqual(got["historical_content_status"], "identical", got["historical_content_reason"])


if __name__ == "__main__":
    unittest.main()
