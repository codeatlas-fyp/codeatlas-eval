"""Related PRs that count as one case (audit 21 Nov, point 6): eval/case_groups.csv.

Two PRs are one case group when they are not independent units: a revert and its original, a follow-up fix of the
same change, or two PRs implementing the same Jira issue that the team judged to be one piece of work. The team
decides each group and records it here, with the reason and the date; nothing is grouped automatically.

    group_id,repo,pr_number,reason,decided_on
    G-01,airflow,6241,"same work as #6783 (AIRFLOW-3014)",2026-11-22
    G-01,airflow,6783,"same work as #6241 (AIRFLOW-3014)",2026-11-22

The sampler takes at most one PR per group, the freezer writes the group into case.yaml, and dev_cases.py keeps
dev cases out of every group the scored cases use. shared_keys() lists PRs that share a Jira key so the team can
decide whether they are a group; sharing a key alone does not make them one.
"""

from __future__ import annotations

import re
from pathlib import Path

from common import EVAL, read_csv

GROUPS_FILE = EVAL / "case_groups.csv"
GROUP_FIELDS = ["group_id", "repo", "pr_number", "reason", "decided_on"]


def load_groups(path: Path = GROUPS_FILE) -> dict[tuple[str, str], str]:
    """{(repo, pr_number): group_id}. A PR listed in two groups is an error."""
    out: dict[tuple[str, str], str] = {}
    for row in read_csv(path):
        key = (row["repo"].strip(), row["pr_number"].strip())
        gid = row["group_id"].strip()
        if not gid or not all(key):
            raise SystemExit(f"{path}: every row needs group_id, repo and pr_number ({row})")
        if key in out and out[key] != gid:
            raise SystemExit(f"{path}: {key[0]} #{key[1]} is in two groups ({out[key]}, {gid})")
        out[key] = gid
    return out


def group_of(groups: dict[tuple[str, str], str], repo: str, pr_number: str) -> str:
    return groups.get((repo, str(pr_number)), "")


# leading Jira keys ("[AIRFLOW-1]", "ARROW-2:") and component tags ("[R][CI]") before the first word of the title
_TITLE_PREFIX = re.compile(r"^(?:\s*(?:\[[^\]]*\]|[A-Z][A-Z0-9]+-\d+:?)\s*)*")


def is_revert(row: dict[str, str]) -> bool:
    """True when the PR is a revert: its title, after any leading Jira keys and [tags], starts with "Revert".

    Reverts are excluded as a population rule (Dataset Plan (Final), 21 Nov 2026): their "requirement" is the
    reverted PR's, which confuses criteria labels. A title that only mentions a revert later on is kept.
    """
    title = _TITLE_PREFIX.sub("", row.get("title") or "")
    return re.match(r"revert\b", title, re.IGNORECASE) is not None


def keys_of(row: dict[str, str]) -> set[str]:
    return {k for k in (row.get("jira_keys") or row.get("keys_found") or "").split(";") if k}


def shared_keys(rows: list[dict[str, str]]) -> list[tuple[str, list[str]]]:
    """[(jira key, ["repo #pr", ...])] for every key that two or more of the rows share, sorted by key."""
    by_key: dict[str, list[str]] = {}
    for r in rows:
        for k in keys_of(r):
            by_key.setdefault(k, []).append(f"{r['repo']} #{r['pr_number']}")
    return sorted((k, sorted(v)) for k, v in by_key.items() if len(v) > 1)
