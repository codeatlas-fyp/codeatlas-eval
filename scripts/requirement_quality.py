"""How much requirement text a Jira issue gives (team decision B3).

    unavailable        the issue was not found (not in Jira, not in the mail archive)
    title_only         a summary but no description
    explicit_criteria  the description has a numbered or bulleted list, or says "acceptance criteria"
    descriptive_issue  any other description

The text is the issue as it stood at the decision cutoff when it can be rebuilt (jira_archive.reconstruct_at),
otherwise the saved description. Semantic relevance is labelled only for criteria from explicit_criteria and
descriptive_issue issues; title_only criteria are labelled and reported separately (LABELLING_GUIDE.md, 4).

For a PR with several keys the pool uses the best quality among its verified keys (links.py); if none is
verified, the best among all keys, and requirement_quality_note says so.
"""

from __future__ import annotations

import re
from typing import Any

from jira_archive import reconstruct_at
from links import VERIFIED, parse_locations, pool_key_status

UNAVAILABLE, TITLE_ONLY, EXPLICIT, DESCRIPTIVE = "unavailable", "title_only", "explicit_criteria", "descriptive_issue"
RANK = {EXPLICIT: 0, DESCRIPTIVE: 1, TITLE_ONLY: 2, UNAVAILABLE: 3}
# Jira wiki and Markdown lists: "* a", "- a", "# a" (Jira numbered), "1. a", "1) a", "a) a"; at least one space after
LIST_ITEM = re.compile(r"^\s*(?:[*\-•+]{1,3}|#{1,3}|\d{1,2}[.)]|[a-z][.)])\s+\S", re.MULTILINE)
CRITERIA_WORDS = re.compile(r"acceptance\s+criteri(?:a|on)", re.IGNORECASE)
HEADING = re.compile(r"^\s*h[1-6]\.\s", re.MULTILINE)   # Jira "h3. Title" is a heading, not a list


def classify_text(description: str | None) -> str:
    text = (description or "").strip()
    if not text:
        return TITLE_ONLY
    if CRITERIA_WORDS.search(text) or LIST_ITEM.search(HEADING.sub("", text)):
        return EXPLICIT
    return DESCRIPTIVE


def description_for(issue: dict[str, Any], cutoff: str | None) -> str:
    """The description at the cutoff if it can be rebuilt, else the saved one."""
    if cutoff:
        r = reconstruct_at(issue, cutoff)
        if r["status"] == "reconstructed":
            return r["description"]
    return (issue.get("fields") or {}).get("description") or ""


def classify_issue(issue: dict[str, Any] | None, cutoff: str | None = None) -> str:
    if not issue:
        return UNAVAILABLE
    return classify_text(description_for(issue, cutoff))


def best(qualities: list[str]) -> str:
    return min(qualities, key=lambda q: RANK[q]) if qualities else ""


def row_quality(key_locations: str, quality_by_key: dict[str, str]) -> tuple[str, str]:
    """(requirement_quality, note) for a pool row from its keys' locations and each key's quality."""
    locs = parse_locations(key_locations)
    if not locs:
        return "", "no Jira key"
    verified = [k for k, v in locs.items() if pool_key_status(v) == VERIFIED]
    keys = verified or sorted(locs)
    q = best([quality_by_key.get(k, UNAVAILABLE) for k in keys])
    if verified:
        return q, "" if len(locs) == 1 else f"best of verified keys {';'.join(sorted(verified))}"
    return q, "no verified key: best among all keys"
