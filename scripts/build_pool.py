"""Build the candidate pool for one repository (build plan C5 step 1, C6 pool columns).

Usage:
    python scripts/build_pool.py --repo libcloud            # uses the window in eval/repos.json
    python scripts/build_pool.py --repo airflow --jira      # also reads Jira to flag edited requirements
    python scripts/build_pool.py --repo airflow --limit 50  # stop after 50 new PRs (resumable)
    python scripts/build_pool.py --repo arrow --recheck-unmerged   # redo rows an older run excluded as unmerged

Writes eval/pool/<repo>_pool.csv. Every candidate PR gets a row; excluded rows keep their reason
(rows are never deleted). Raw API responses are cached in eval/pool/raw/ (git-ignored); a PR whose four cached
files already exist is read from the cache instead of the API.
The provisional category comes from source metadata only, never from CodeAtlas output. Only APPROVED reviews
submitted at or before the merge count; a review given after the merge did not support it. Keyed PRs
with no approval on the head commit at or before the merge are no_approval, a sampling category, not a label.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (EVAL, codeowners_at, dump_json, ensure_clone, find_keys, first_parent_commits, gh, is_team, jira_issue_for,
                    merged_branch_messages, owners_for, parse_codeowners, pr_number, read_csv, repo_cfg, write_csv)
from history import pin
from jira_archive import CACHE_SOURCE
from links import pool_link_status

# api_base_sha/api_head_sha are GitHub's base/head, kept only for comparison; evidence uses the refs pinned from the
# merge commit (base_at_merge, head_at_merge, merge_base_sha; scripts/history.py).
FIELDS = ["repo", "pr_number", "pr_url", "merged_at", "api_base_sha", "api_head_sha", "merge_commit_sha", "merge_strategy",
          "base_at_merge", "head_at_merge", "merge_base_sha", "historical_diff_status", "historical_diff_reason", "title",
          "keys_found", "key_locations", "link_status", "requirement_quality", "requirement_quality_note", "py_files_changed", "files_changed", "review_count", "approvals_on_head",
          "codeowners_present", "provisional_category", "included", "exclusion_reason", "merged_via"]
MAX_FILES = 20
BOT_TITLE = re.compile(r"^\s*(bump |build\(deps|chore\(deps|\[?release\b|prepare release|update changelog)", re.IGNORECASE)


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def utc_z(iso: str) -> str:
    """Any ISO time with an offset -> GitHub's UTC form, e.g. 2022-04-05T08:11:12Z."""
    return ts(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def migrate_row(row: dict[str, str]) -> dict[str, str]:
    """A row written before the history columns existed: base_sha/head_sha were the API's, so rename them."""
    for old, new in (("base_sha", "api_base_sha"), ("head_sha", "api_head_sha")):
        if old in row and not row.get(new):
            row[new] = row.pop(old)
    return row


def cached_pr(raw: Path) -> tuple[Any, Any, Any, Any] | None:
    """(pr, files, reviews, commits) from eval/pool/raw/<repo>/<n>/ when all four were saved, else None."""
    paths = [raw / f"{name}.json" for name in ("pr", "files", "reviews", "commits")]
    if not all(p.exists() for p in paths):
        return None
    try:
        pr, files, reviews, commits = (json.loads(p.read_text(encoding="utf-8")) for p in paths)
    except json.JSONDecodeError:  # a file cut short by a crash: fetch again
        return None
    return pr, files, reviews, commits


def merge_time(pr: dict[str, Any], commit: dict[str, str]) -> tuple[str, str]:
    """(merged_at, how) for a PR whose commit sits on the main branch's first-parent line.

    GitHub's merge button sets merged_at. Arrow and Spark merge with a script (merge_arrow_pr.py, merge_spark_pr.py)
    that pushes the squashed commit to the main branch with "Closes #N" and closes the PR, so GitHub leaves
    merged_at empty. Such a PR is merged all the same: its commit is on the main branch (that is how this script
    found it). Its merge time is that commit's committer time. A PR that is still open is not merged.
    """
    if pr.get("merged_at"):
        return pr["merged_at"], "github"
    if pr.get("state") == "closed":
        return utc_z(commit["time"]), f"script (commit {commit['sha'][:10]} on main)"
    return "", ""


def approvals_by_merge(reviews: list[dict[str, Any]], merged_at: str) -> list[dict[str, Any]]:
    """APPROVED reviews submitted at or before the merge. A review given after the merge did not support it."""
    if not merged_at:
        return []
    return [r for r in reviews if r.get("state") == "APPROVED" and r.get("submitted_at")
            and ts(r["submitted_at"]) <= ts(merged_at)]


def approvers_on(approvals: list[dict[str, Any]], head: str) -> set[str]:
    """Logins (lower case) whose approval was given on the head commit."""
    return {r["user"]["login"].lower() for r in approvals if r.get("commit_id") == head and r.get("user")}


def owner_info(co_text: str | None, py: list[str]) -> tuple[list[list[str]], set[str], bool]:
    """(matched owner lists, user owners, all owners are teams) for the .py files under CODEOWNERS."""
    rules = parse_codeowners(co_text) if co_text else []
    owner_sets = [owners_for(p, rules) for p in py] if rules else []
    matched = [o for o in owner_sets if o]
    user_owners = {o.lstrip("@").lower() for os_ in matched for o in os_ if not is_team(o) and o.startswith("@")}
    all_team = bool(matched) and all(all(is_team(o) for o in os_) for os_ in matched)
    return matched, user_owners, all_team


def approval_category(approvals: list[dict[str, Any]], approvers_on_head: set[str], matched: list[list[str]],
                      user_owners: set[str], all_team: bool) -> str:
    """Provisional category of a keyed PR whose requirement did not change, from approvals at or before merge."""
    if approvals and not approvers_on_head:
        return "ownership_gap"            # approval only on an older commit
    if all_team:
        return "ownership_gap"            # owners are teams; membership at cutoff not visible
    if approvers_on_head and (not matched or approvers_on_head & user_owners):
        return "supported_approval"
    # keyed PR with no approval on the head commit at or before the merge. A sampling category, not a label:
    # whether the PR was allowed to merge is what the annotators decide (B1; formerly needs_manual)
    return "no_approval"


def requirement_edited(cfg: dict[str, Any], keys: list[str], work_began: str, merged_at: str, raw_dir: Path) -> bool | None:
    """True if a summary/description edit happened after the first commit and before the merge."""
    edited = False
    for key in keys:
        try:
            issue = jira_issue_for(cfg, key, raw_dir.name)   # a cached REST copy is preferred
        except Exception as e:  # noqa: BLE001 - record, do not guess
            print(f"  jira {key}: {e}")
            return None
        if issue.get("source") != CACHE_SOURCE:   # never overwrite a cached REST copy with an archive copy
            dump_json(raw_dir / f"jira_{key}.json", issue)
        for h in issue.get("changelog", {}).get("histories", []):
            at = ts(h["created"].replace("+0000", "+00:00"))
            if ts(work_began) < at <= ts(merged_at) and any(i.get("field") in ("summary", "description") for i in h.get("items", [])):
                edited = True
    return edited


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jira", action="store_true")
    ap.add_argument("--recheck-unmerged", action="store_true",
                    help="drop rows an older run excluded as 'not merged on GitHub' and classify them again")
    a = ap.parse_args()

    cfg = repo_cfg(a.repo)
    since = a.since or cfg["window"]["since"]
    until = a.until or cfg["window"]["until"]
    if not (since and until):
        raise SystemExit("set the window in eval/repos.json or pass --since/--until")
    repo = ensure_clone(cfg)
    out = EVAL / "pool" / f"{cfg['name']}_pool.csv"
    rows = [migrate_row(r) for r in read_csv(out)]
    if a.recheck_unmerged:
        before = len(rows)
        rows = [r for r in rows if not r.get("exclusion_reason", "").startswith("not merged on GitHub")]
        print(f"rechecking {before - len(rows)} rows excluded as unmerged by an older run")
    done = {r["pr_number"] for r in rows}
    root = cfg["analysis_root"]
    new = 0

    for c in first_parent_commits(repo, since, until):
        n = pr_number(c["subject"], c["body"])
        if n is None or str(n) in done:
            continue
        if a.limit and new >= a.limit:
            break
        new += 1
        raw = EVAL / "pool" / "raw" / cfg["name"] / str(n)
        cached = cached_pr(raw)
        if cached:
            pr, files, reviews, commits = cached
        else:
            pr = gh(f"repos/{cfg['github']}/pulls/{n}")
            files = gh(f"repos/{cfg['github']}/pulls/{n}/files", paginate=True)
            reviews = gh(f"repos/{cfg['github']}/pulls/{n}/reviews", paginate=True)
            commits = gh(f"repos/{cfg['github']}/pulls/{n}/commits", paginate=True)
            for name, data in (("pr", pr), ("files", files), ("reviews", reviews), ("commits", commits)):
                dump_json(raw / f"{name}.json", data)

        # keys and where they were found
        where: dict[str, set[str]] = {}
        sources = {"title": pr.get("title", ""), "branch": pr.get("head", {}).get("ref", ""), "body": pr.get("body") or "",
                   "commit": "\n".join(x["commit"]["message"] for x in commits) + "\n" + merged_branch_messages(repo, c),
                   # the main-branch commit itself, subject included (script merges put the key there; A5)
                   "merge_commit": c["subject"] + "\n" + c["body"]}
        for loc, text in sources.items():
            for k in find_keys(text, cfg["key_regex"]):
                where.setdefault(k, set()).add(loc)
        keys = sorted(where)

        paths = [f["filename"] for f in files]
        py = [p for p in paths if p.endswith(".py") and p.startswith(root)]
        head = pr["head"]["sha"]
        base = pr["base"]["sha"]
        merged_at, merged_via = merge_time(pr, c)
        # only approvals submitted at or before the merge count (A4)
        approvals = approvals_by_merge(reviews, merged_at)
        approvers_on_head = approvers_on(approvals, head)

        hist = pin(repo, c["sha"], n, files, api_base=base, api_head=head)
        # CODEOWNERS as it stood on the base branch at the merge, not at GitHub's (movable) API base
        co_path, co_text = codeowners_at(repo, hist["base_at_merge"]) if hist["base_at_merge"] else (None, None)
        matched, user_owners, all_team = owner_info(co_text, py)

        # inclusion rules (C4)
        login = (pr.get("user") or {}).get("login", "")
        reason = ""
        if not merged_at:
            reason = "not merged (PR still open)"
        elif not py:
            reason = f"no .py file under '{root or '/'}'"
        elif len(paths) > MAX_FILES:
            reason = f"{len(paths)} files changed (> {MAX_FILES})"
        elif login.endswith("[bot]") or (pr.get("user") or {}).get("type") == "Bot" or BOT_TITLE.search(pr.get("title", "")):
            reason = "bot or release PR"

        # provisional category from metadata only
        if not keys:
            cat = "no_key"
        elif a.jira and requirement_edited(cfg, keys, commits[0]["commit"]["committer"]["date"] if commits else pr["created_at"],
                                           merged_at or pr["closed_at"], raw):
            cat = "requirement_changed"
        else:
            cat = approval_category(approvals, approvers_on_head, matched, user_owners, all_team)

        rows.append(hist | {
            "repo": cfg["name"], "pr_number": n, "pr_url": pr["html_url"], "merged_at": merged_at,
            "title": pr.get("title", ""),
            "keys_found": ";".join(keys), "key_locations": ";".join(f"{k}:{'+'.join(sorted(v))}" for k, v in sorted(where.items())),
            "link_status": pool_link_status(";".join(f"{k}:{'+'.join(sorted(v))}" for k, v in sorted(where.items()))),
            "py_files_changed": len(py), "files_changed": len(paths), "review_count": len(reviews),
            "approvals_on_head": len(approvers_on_head), "codeowners_present": co_path or "no",
            "provisional_category": cat, "included": "no" if reason else "yes", "exclusion_reason": reason,
            "merged_via": merged_via,
        })
        write_csv(out, rows, FIELDS)   # write after every PR so a crash loses nothing
        print(f"#{n:<6} {cat:<20} {'excluded: ' + reason if reason else 'included'}")

    print(f"\n{len(rows)} rows in {out} ({new} new). Related PRs (revert + original, follow-up fix) must be grouped by hand.")


if __name__ == "__main__":
    main()
