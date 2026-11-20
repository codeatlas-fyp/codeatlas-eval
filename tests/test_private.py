"""Tests for scripts/pseudonymise.py and scripts/audit_private.py (A6; standard library only, no network).

    python -m unittest discover -s tests -v

Real-looking addresses and tokens are put together at run time, so this file itself passes the audit.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import audit_private as ap
import pseudonymise as ps

AT = "@"
JANE = "jane.doe" + AT + "corp.io"
BOB = "bob" + AT + "mail.example.org"
GH_TOKEN = "ghp" + "_" + "A1b2C3d4" * 5


class PseudonymiseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.map = self.tmp / "local" / "pseudonyms.yaml"

    def tearDown(self):
        self._tmp.cleanup()

    def run_on(self, name, text):
        f = self.tmp / name
        f.write_text(text, encoding="utf-8")
        ps.pseudonymise_file(f, map_path=self.map)
        return f.read_text(encoding="utf-8")

    def test_emails_and_logins_replaced(self):
        data = {"user": {"login": "JaneDev", "html_url": "https://github.com/JaneDev"},
                "body": f"thanks @bobsmith, mail {JANE}; team @apache/airflow-committers"}
        out = self.run_on("reviews.json", json.dumps(data))
        for real in ("JaneDev", "bobsmith", JANE):
            self.assertNotIn(real, out)
        self.assertIn('"login": "user-0', out)
        self.assertIn("https://github.com/user-0", out)
        self.assertIn("@apache/airflow-committers", out)   # a team handle is not a person
        json.loads(out)                                     # still valid JSON

    def test_pseudonyms_are_stable_across_files_and_runs(self):
        first = self.run_on("a.txt", f"{JANE} and {BOB}")
        second = self.run_on("b.txt", f"{BOB} then {JANE}")
        self.assertEqual(first, "user-01 and user-02")
        self.assertEqual(second, "user-02 then user-01")
        mapping = ps.load_map(self.map)
        self.assertEqual(mapping[JANE], "user-01")
        self.assertEqual(sorted(mapping.values()), ["user-01", "user-02"])

    def test_same_login_any_case_gets_one_pseudonym(self):
        out = self.run_on("c.txt", '{"login": "Alice"} cc @alice')
        self.assertEqual(out, '{"login": "user-01"} cc @user-01')

    def test_allowed_addresses_kept(self):
        text = "a" + AT + "example.test commits" + AT + "airflow.apache.org 1+x" + AT + "users.noreply.github.com"
        self.assertEqual(self.run_on("d.txt", text), text)

    def test_map_folder_created_and_map_never_in_repo(self):
        self.run_on("e.txt", JANE)
        self.assertTrue(self.map.exists())
        with self.assertRaises(SystemExit):
            ps.main([str(self.tmp / "e.txt"), "--map", str(ps.ROOT / "pseudonyms.yaml")])

    def test_default_map_is_outside_the_repo(self):
        self.assertFalse(ps.DEFAULT_MAP.resolve().is_relative_to(ps.ROOT))
        self.assertEqual(ps.DEFAULT_MAP.parent.name, "codeatlas-local")


class AuditTests(unittest.TestCase):
    def audit(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for name, text in files.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                paths.append(p)
            return ap.audit(paths, root)

    def test_real_email_fails(self):
        problems = self.audit({"notes.md": f"line one\nwritten by {JANE}\n"})
        self.assertEqual(problems, ["notes.md:2: e-mail address"])

    def test_allowed_addresses_pass(self):
        text = ("t" + AT + "example.test, x" + AT + "example.com, 9+me" + AT + "users.noreply.github.com, "
                "issues" + AT + "arrow.apache.org, dev" + AT + "spark.apache.org")
        self.assertEqual(self.audit({"ok.md": text}), [])

    def test_personal_apache_address_fails(self):
        self.assertEqual(len(self.audit({"x.md": "jdoe" + AT + "apache.org"})), 1)

    def test_token_fails_without_printing_it(self):
        problems = self.audit({"cfg.txt": f"token = {GH_TOKEN}\n"})
        self.assertEqual(problems, ["cfg.txt:1: GitHub token"])
        self.assertNotIn(GH_TOKEN, "".join(problems))

    def test_tracked_pseudonym_map_or_sources_fail(self):
        problems = self.audit({"eval/pseudonyms.yaml": "# map\n", "eval/cases/AF-01/sources/pr.json": "{}\n"})
        self.assertEqual(len(problems), 2)

    def test_main_on_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "a.md").write_text(f"contact {JANE}\n", encoding="utf-8")
            subprocess.run(["git", "add", "a.md"], cwd=root, check=True)
            self.assertEqual([p.name for p in ap.tracked_files(root)], ["a.md"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ap.main([str(root / "a.md")]), 1)

    def test_repository_passes_the_audit(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = ap.main([])
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
