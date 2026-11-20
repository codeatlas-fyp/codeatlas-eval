"""Tests for PRs with several Jira keys (B4): freeze_case.collect, scripts/scoring.py and the label templates.

    python -m unittest discover -s tests -v

collect() runs against a temporary Git repository; GitHub, Jira and the history pin are replaced by fakes.
"""

from __future__ import annotations

import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import freeze_case as fc
import scoring

TEMPLATES = Path(__file__).resolve().parent.parent / "eval" / "templates"
MERGED = "2019-10-01T12:00:00Z"
CFG = {"name": "airflow", "github": "apache/airflow", "jira_base": "https://jira.example.test",
       "key_regex": r"\bAIRFLOW-\d+\b", "analysis_root": ""}


def make_repo(root: Path) -> str:
    git = ["git", "-c", "user.name=T", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=root, check=True)
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "a.py"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "fix the hook (#9)"], cwd=root, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()


def fake_gh(path, paginate=False):
    if path.endswith("/pulls/9"):
        return {"title": "[AIRFLOW-1] fix the hook", "body": "see also AIRFLOW-2", "merged_at": MERGED,
                "html_url": "https://github.com/apache/airflow/pull/9", "head": {"ref": "fix", "sha": "h"},
                "base": {"sha": "b"}}
    if path.endswith("/commits"):
        return [{"commit": {"message": "AIRFLOW-3 part one"}}]
    if path.endswith("/timeline"):
        return []
    return []


def fake_issue(base, key):
    if key == "AIRFLOW-3":
        raise PermissionError("HTTP 401")
    return {"key": key, "source": "jira_rest", "fields": {"summary": f"{key} summary", "description": "* do it"},
            "changelog": {"histories": []}}


def fake_pin(repo, merge, n, files, api_base="", api_head="", fetch=True):
    return {"merge_commit_sha": merge, "merge_strategy": "single_parent", "base_at_merge": merge,
            "head_at_merge": "h", "merge_base_sha": merge, "historical_diff_status": "verified",
            "historical_diff_reason": "", "api_base_sha": api_base, "api_head_sha": api_head}


class FreezeAllKeysTests(unittest.TestCase):
    def collect(self, tmp: Path, row_keys: str, gh=fake_gh) -> tuple[Path, str]:
        repo = tmp / "repo"
        repo.mkdir()
        sha = make_repo(repo)
        case = tmp / "AF-01.staging"
        case.mkdir()
        row = {"case_id": "AF-01", "set": "pilot", "repo": "airflow", "pr_number": "9", "jira_keys": row_keys,
               "merge_commit_sha": sha, "decision_cutoff_utc": MERGED, "category_provisional": "supported_approval"}
        policies = tmp / "policies"
        policies.mkdir()
        (policies / "airflow.yaml").write_text("# Baseline policy v0.1 - status: DRAFT\nversion: 1\n", encoding="utf-8")
        with mock.patch.object(fc, "repo_cfg", return_value=CFG), mock.patch.object(fc, "ensure_clone", return_value=repo), \
                mock.patch.object(fc, "gh", side_effect=gh), mock.patch.object(fc, "jira_issue_for", side_effect=lambda cfg, key, pr=None: fake_issue(cfg, key)), \
                mock.patch.object(fc, "pin", side_effect=fake_pin), mock.patch.object(fc, "POLICIES", policies, create=True), \
                contextlib.redirect_stdout(io.StringIO()):
            fc.collect(row, case)
        return case, (case / "case.yaml").read_text(encoding="utf-8")

    def test_every_key_of_a_multi_key_pr_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            case, text = self.collect(Path(tmp), "AIRFLOW-1")
            for key in ("AIRFLOW-1", "AIRFLOW-2", "AIRFLOW-3"):
                at = (case / "sources" / f"jira_{key}_at_cutoff.txt").read_text(encoding="utf-8")
                self.assertIn(f"key: {key}", at)
                self.assertIn("reconstruction_status:", at)
            self.assertTrue((case / "sources" / "jira_AIRFLOW-3.INACCESSIBLE.txt").exists())
        links = re.findall(r"^  - \{key: (AIRFLOW-\d), .*status: (\w+), requirement_quality: (\w+), "
                           r"reconstruction_status: (\w+)", text, flags=re.MULTILINE)
        self.assertEqual(links, [("AIRFLOW-1", "verified", "explicit_criteria", "reconstructed"),
                                 ("AIRFLOW-3", "verified", "unavailable", "inaccessible"),
                                 ("AIRFLOW-2", "uncertain", "explicit_criteria", "reconstructed")])

    def test_case_without_keys_has_empty_links(self):
        def no_key_gh(path, paginate=False):
            if path.endswith("/pulls/9"):
                return {**fake_gh(path), "title": "fix", "body": ""}
            if path.endswith("/commits"):
                return [{"commit": {"message": "wip"}}]
            return []

        with tempfile.TemporaryDirectory() as tmp:
            _, text = self.collect(Path(tmp), "", gh=no_key_gh)
        self.assertIn("jira_links: []", text)


LINKS = [{"key": "AIRFLOW-1", "status": "verified"}, {"key": "AIRFLOW-2", "status": "verified"},
         {"key": "AIRFLOW-3", "status": "uncertain"}]


class ScoredKeysTests(unittest.TestCase):
    def test_uncertain_key_is_never_scored(self):
        rel = {"AIRFLOW-1": "relevant", "AIRFLOW-2": "relevant", "AIRFLOW-3": "relevant"}
        self.assertEqual(scoring.scored_keys(LINKS, rel), ["AIRFLOW-1", "AIRFLOW-2"])

    def test_not_relevant_and_unclear_keys_are_not_scored(self):
        rel = {"AIRFLOW-1": "relevant", "AIRFLOW-2": "not_relevant"}
        self.assertEqual(scoring.scored_keys(LINKS, rel), ["AIRFLOW-1"])
        self.assertEqual(scoring.scored_keys(LINKS, {"AIRFLOW-1": "unclear"}), [])

    def test_case_with_no_scored_key_is_kept_with_insufficient_evidence(self):
        labels = {f"C{i}": "SATISFIED" for i in range(1, 10)}
        got = scoring.requirement_rule_results(LINKS, {"AIRFLOW-3": "relevant"}, labels)
        self.assertEqual(got["scored_keys"], [])
        self.assertTrue(got["in_coverage"])
        for rule in ("C1", "C3", "C4", "C6", "C8", "C9"):
            self.assertEqual(got["rules"][rule], "INSUFFICIENT_EVIDENCE")
        for rule in ("C2", "C5", "C7"):
            self.assertEqual(got["rules"][rule], "SATISFIED")

    def test_criteria_follow_their_key(self):
        crit = [{"criterion_id": "AIRFLOW-1:v1:ac1"}, {"criterion_id": "AIRFLOW-2:v1:ac1"}]
        self.assertEqual(scoring.scored_criteria(crit, ["AIRFLOW-2"]), [{"criterion_id": "AIRFLOW-2:v1:ac1"}])


class TemplateTests(unittest.TestCase):
    BLOCK = ('  - key: ""\n', '    relevance: ""        # relevant | not_relevant | unclear\n',
             '    reason: ""           # one line citing the source\n')

    def test_label_template_has_the_jira_links_block(self):
        text = (TEMPLATES / "label.yaml").read_text(encoding="utf-8")
        self.assertIn("jira_links:", text)
        self.assertIn("".join(self.BLOCK), text)
        self.assertLess(text.index("jira_links:"), text.index("rules:"))

    def test_adjudicated_template_has_the_jira_links_block(self):
        text = (TEMPLATES / "adjudicated.yaml").read_text(encoding="utf-8")
        self.assertIn("".join("  " + line for line in self.BLOCK), text)

    def test_no_single_key_placeholder_left(self):
        for name in ("label.yaml", "adjudicated.yaml", "case.yaml"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"jira_key:|jira_version_at_cutoff", name)


if __name__ == "__main__":
    unittest.main()
