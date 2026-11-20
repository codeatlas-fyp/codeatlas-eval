"""Tests for keys whose edit history is unknown (created_text_only): scripts/scoring.py, eval/rules_scope.yaml,
eval/scoring_rules.md and the sampling report (standard library only, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_cases as sc
import scoring
from test_rules_scope import read_scope

EVAL = Path(__file__).resolve().parent.parent / "eval"
SATISFIED = {f"C{i}": "SATISFIED" for i in range(1, 10)}


def link(key, status="verified", rec="reconstructed"):
    return {"key": key, "status": status, "reconstruction_status": rec}


class HistoryUnknownScoringTests(unittest.TestCase):
    def test_created_text_only_key_never_satisfies_c1_or_c6(self):
        got = scoring.requirement_rule_results([link("ARROW-1", rec="created_text_only")], {"ARROW-1": "relevant"},
                                               SATISFIED)
        self.assertEqual(got["rules"]["C1"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(got["rules"]["C6"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(got["rules"]["C3"], "SATISFIED")        # other rules untouched
        self.assertEqual(got["history_unknown_keys"], ["ARROW-1"])
        self.assertEqual(got["scored_keys"], ["ARROW-1"])

    def test_violation_from_a_key_with_known_history_stands(self):
        links = [link("ARROW-1", rec="created_text_only"), link("ARROW-2", rec="jira_rest_cache")]
        labels = SATISFIED | {"C1": "VIOLATED", "C6": "SATISFIED"}
        got = scoring.requirement_rule_results(links, {"ARROW-1": "relevant", "ARROW-2": "relevant"}, labels)
        self.assertEqual(got["rules"]["C1"], "VIOLATED")
        self.assertEqual(got["rules"]["C6"], "INSUFFICIENT_EVIDENCE")

    def test_violation_with_only_unknown_history_is_insufficient(self):
        got = scoring.requirement_rule_results([link("ARROW-1", rec="created_text_only")], {"ARROW-1": "relevant"},
                                               SATISFIED | {"C1": "VIOLATED"})
        self.assertEqual(got["rules"]["C1"], "INSUFFICIENT_EVIDENCE")

    def test_unscored_created_text_only_key_changes_nothing(self):
        links = [link("ARROW-1", rec="created_text_only"), link("ARROW-2")]
        got = scoring.requirement_rule_results(links, {"ARROW-1": "not_relevant", "ARROW-2": "relevant"}, SATISFIED)
        self.assertEqual(got["rules"]["C1"], "SATISFIED")
        self.assertEqual(got["history_unknown_keys"], [])

    def test_pool_history_column(self):
        self.assertEqual(scoring.history_unknown("ARROW-1:jira_rest_cache;ARROW-2:created_text_only"), ["ARROW-2"])
        self.assertEqual(scoring.history_unknown(""), [])


class DocumentedRuleTests(unittest.TestCase):
    def test_rules_scope_c1_and_c6(self):
        scope = read_scope()
        for rule in ("C1", "C6"):
            text = scope[rule].get("when_history_unknown", "")
            self.assertIn("created_text_only", text, rule)
            self.assertIn("INSUFFICIENT_EVIDENCE", text, rule)
            self.assertIn("never SATISFIED", text, rule)

    def test_scoring_rules_section(self):
        text = (EVAL / "scoring_rules.md").read_text(encoding="utf-8")
        self.assertIn("## Keys whose edit history is unknown (created_text_only)", text)
        self.assertIn("never\n  SATISFIED", text)
        self.assertIn("cannot be proven unchanged", text)


class SamplingReportTests(unittest.TestCase):
    def test_rows_with_unknown_history_are_reported_separately(self):
        rows = [{"pr_number": "7", "provisional_category": "supported_approval", "keys_found": "ARROW-1",
                 "key_locations": "ARROW-1:commit", "jira_history": "ARROW-1:created_text_only", "merged_at": "x"},
                {"pr_number": "8", "provisional_category": "no_approval", "keys_found": "ARROW-2",
                 "key_locations": "ARROW-2:commit", "jira_history": "ARROW-2:jira_rest_cache", "merged_at": "y"}]
        avail = {"arrow": {c: 0 for c in sc.QUOTAS}}
        alloc = {"arrow": {c: 0 for c in sc.QUOTAS}}
        lines = sc.report(1, ["arrow"], {}, avail, alloc, [], {"arrow": rows})
        text = "\n".join(lines)
        self.assertIn("## Requirement not proven unchanged (edit history unknown)", text)
        self.assertIn("| arrow | 1 | #7 supported_approval |", text)


if __name__ == "__main__":
    unittest.main()
