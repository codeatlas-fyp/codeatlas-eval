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
# rules that need the issue's edit history; a key whose history is unknown (created_text_only: the mail archive has
# only its Created email) can never make them SATISFIED
HISTORY_RULES = ("C1", "C6")
HISTORY_UNKNOWN = "created_text_only"


def scored_keys(jira_links: list[dict[str, Any]], relevance: dict[str, str]) -> list[str]:
    """Keys with status verified and adjudicated relevance relevant, in jira_links order."""
    return [x["key"] for x in jira_links if x.get("status") == "verified" and relevance.get(x["key"]) == "relevant"]


def requirement_rule_results(jira_links: list[dict[str, Any]], relevance: dict[str, str],
                             labels: dict[str, str]) -> dict[str, Any]:
    """The labels to score for one case: without a scored key, requirement rules are INSUFFICIENT_EVIDENCE.

    A scored key with reconstruction_status created_text_only has an unknown edit history: C1 and C6 become
    INSUFFICIENT_EVIDENCE (never SATISFIED); a VIOLATED label stays only if another scored key, whose history is
    known, can carry it. Such keys are returned in history_unknown_keys so they are reported separately.

    Returns scored_keys, rules ({rule: result}), in_coverage (always True: such a case is never dropped),
    history_unknown_keys.
    """
    keys = scored_keys(jira_links, relevance)
    rules = dict(labels)
    if not keys:
        for rule in REQUIREMENT_RULES:
            rules[rule] = "INSUFFICIENT_EVIDENCE"
    status = {x["key"]: x.get("reconstruction_status", "") for x in jira_links}
    unknown = [k for k in keys if status.get(k) == HISTORY_UNKNOWN]
    known = [k for k in keys if k not in unknown]
    if unknown:
        for rule in HISTORY_RULES:
            if not (rules.get(rule) == "VIOLATED" and known):
                rules[rule] = "INSUFFICIENT_EVIDENCE"
    return {"scored_keys": keys, "rules": rules, "in_coverage": True, "history_unknown_keys": unknown}


def history_unknown(jira_history: str) -> list[str]:
    """Keys of a pool row whose edit history is unknown, from its jira_history column (KEY:status;...)."""
    return [part.split(":", 1)[0] for part in (jira_history or "").split(";")
            if part.endswith(":" + HISTORY_UNKNOWN)]


def scored_criteria(criteria: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """Criteria tagged with a scored key (criterion_id starts with '<KEY>:')."""
    return [c for c in criteria if c.get("criterion_id", "").split(":", 1)[0] in keys]
