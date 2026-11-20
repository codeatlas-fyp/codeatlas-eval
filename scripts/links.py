"""How well a Jira key is tied to a PR (integrity fix A5).

Where a key was found decides how far it can be trusted as the PR's requirement at the merge:

- commit message, branch name or the merge commit: written as part of the change itself -> "verified";
- PR title: titles can be renamed after the merge. The key is "verified" only if the PR timeline
  (issues/<n>/timeline, "renamed" events) shows that the title in force at the merge contained it;
- PR description only (or a title we could not check): "uncertain". Descriptions can be edited at any time and
  GitHub keeps no history of them that the API returns.

The pool has no timeline, so its `link_status` column uses "title_unchecked" for a key found in the title
(and not in a commit or the branch); freeze_case.py does the full check with the timeline.
A row's link_status is the best status among its keys: verified > title_unchecked > uncertain.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

VERIFIED, TITLE_UNCHECKED, UNCERTAIN = "verified", "title_unchecked", "uncertain"
RANK = {VERIFIED: 0, TITLE_UNCHECKED: 1, UNCERTAIN: 2}
STRONG_LOCATIONS = {"commit", "branch", "merge_commit"}


def parse_locations(key_locations: str) -> dict[str, set[str]]:
    """'AIRFLOW-1:body+title;AIRFLOW-2:commit' -> {'AIRFLOW-1': {'body', 'title'}, 'AIRFLOW-2': {'commit'}}"""
    out: dict[str, set[str]] = {}
    for part in (key_locations or "").split(";"):
        if ":" in part:
            key, locs = part.split(":", 1)
            out[key] = {x for x in locs.split("+") if x}
    return out


def pool_key_status(locations: set[str]) -> str:
    """Status of one key from where it was found, without network."""
    if locations & STRONG_LOCATIONS:
        return VERIFIED
    if "title" in locations:
        return TITLE_UNCHECKED
    return UNCERTAIN


def best(statuses: list[str]) -> str:
    return min(statuses, key=lambda s: RANK[s]) if statuses else ""


def pool_link_status(key_locations: str) -> str:
    """The pool's link_status column: the best key status of the row, '' for a row without keys."""
    return best([pool_key_status(v) for v in parse_locations(key_locations).values()])


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def title_at(current_title: str, timeline: list[dict[str, Any]], cutoff: str) -> str:
    """The PR title in force at the cutoff: the current title with every later rename undone, newest first."""
    renames = sorted((e for e in timeline if e.get("event") == "renamed" and e.get("created_at")),
                     key=lambda e: _utc(e["created_at"]))
    title = current_title
    for e in reversed(renames):
        if _utc(e["created_at"]) <= _utc(cutoff):
            break
        title = (e.get("rename") or {}).get("from", title)
    return title


def freeze_link_statuses(where: dict[str, set[str]], title_at_merge: str | None, key_regex: str) -> list[dict[str, Any]]:
    """Full check at freeze time. title_at_merge is None when the timeline could not be read.

    Returns one entry per key: key, found_in (sorted locations), status (verified | uncertain), reason.
    A key that was in the title at the merge but was renamed away later is added with found_in title_at_merge.
    """
    where = {k: set(v) for k, v in where.items()}
    if title_at_merge is not None:
        for k in {m.upper() for m in re.findall(key_regex, title_at_merge, flags=re.IGNORECASE)}:
            where.setdefault(k, set()).add("title_at_merge")
    out = []
    for key, locs in sorted(where.items()):
        strong = sorted(locs & STRONG_LOCATIONS)
        if strong:
            status, reason = VERIFIED, f"in {', '.join(strong)}"
        elif ("title" in locs or "title_at_merge" in locs) and title_at_merge is None:
            status, reason = UNCERTAIN, "in the PR title, but the timeline could not be read to check it at the merge"
        elif "title_at_merge" in locs:
            status, reason = VERIFIED, "in the PR title in force at the merge (timeline renamed events)"
        elif "title" in locs:
            status, reason = UNCERTAIN, "only in a PR title set after the merge"
        else:
            status, reason = UNCERTAIN, f"only in {', '.join(sorted(locs)) or 'unknown'}"
        out.append({"key": key, "found_in": sorted(locs), "status": status, "reason": reason})
    return out
