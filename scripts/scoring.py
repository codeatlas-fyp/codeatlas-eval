"""Which Jira keys of a case are scored (team decision B4; eval/scoring_rules.md).

Every historically supported key is frozen and shown to annotators; none is dropped. Only some are scored:
governance rules and semantic criteria use a key only if its link status is "verified" (links.py) AND the
adjudicated relevance is "relevant". "unclear" and "not_relevant" keys are recorded, never scored;
"uncertain" keys are shown, never scored. A case with no scored key keeps INSUFFICIENT_EVIDENCE for the rules
that need a requirement and stays in the coverage counts.

This is the rule only, so the scoring code and the tests share one definition; it is not an evaluation runner.
"""

from __future__ import annotations

from typing import Any

# rules that need a requirement: CodeAtlas answers INSUFFICIENT_EVIDENCE without a work item (C1, C3, C4, C6,
# C8), and the guide does the same for C9 when no linked issue has usable text
REQUIREMENT_RULES = ("C1", "C3", "C4", "C6", "C8", "C9")
RELEVANCE = ("relevant", "not_relevant", "unclear")


def scored_keys(jira_links: list[dict[str, Any]], relevance: dict[str, str]) -> list[str]:
    """Keys with status verified and adjudicated relevance relevant, in jira_links order."""
    return [x["key"] for x in jira_links if x.get("status") == "verified" and relevance.get(x["key"]) == "relevant"]


def requirement_rule_results(jira_links: list[dict[str, Any]], relevance: dict[str, str],
                             labels: dict[str, str]) -> dict[str, Any]:
    """The labels to score for one case: without a scored key, requirement rules are INSUFFICIENT_EVIDENCE.

    Returns scored_keys, rules ({rule: result}), in_coverage (always True: such a case is never dropped).
    """
    keys = scored_keys(jira_links, relevance)
    rules = dict(labels)
    if not keys:
        for rule in REQUIREMENT_RULES:
            rules[rule] = "INSUFFICIENT_EVIDENCE"
    return {"scored_keys": keys, "rules": rules, "in_coverage": True}


def scored_criteria(criteria: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """Criteria tagged with a scored key (criterion_id starts with '<KEY>:')."""
    return [c for c in criteria if c.get("criterion_id", "").split(":", 1)[0] in keys]
