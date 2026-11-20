"""Bring an already-built pool up to the integrity fixes without rebuilding it.

Usage:
    python scripts/update_pool.py --repo airflow --history    # A1: pin refs from the merge commit (clone + PR files)
    python scripts/update_pool.py --repo airflow --reviews    # A4: approvals at or before the merge (reviews endpoint)
    python scripts/update_pool.py --repo airflow --links      # A5: link_status from key_locations and the clone (no network)
    python scripts/update_pool.py --repo airflow --quality    # B3: requirement_quality from the saved issue text

Only included rows are touched; excluded rows keep what they have. GitHub is read with GET only and every answer
is cached in eval/pool/raw/<repo>/<pr>/ (git-ignored), so a rerun reads the cache. The pool is written after
every row, so a crash loses nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_pool import FIELDS, approval_category, approvals_by_merge, approvers_on, migrate_row, owner_info
from common import EVAL, REPOS_DIR, codeowners_at, dump_json, ensure_clone, find_keys, gh, git, read_csv, repo_cfg, write_csv
from history import fetch_pr_heads, pin
from links import parse_locations, pool_link_status
from requirement_quality import UNAVAILABLE, classify_issue, row_quality


def cached_or_fetch(raw: Path, name: str, api_path: str, paginate: bool = True) -> Any:
    """eval/pool/raw/<repo>/<pr>/<name>.json if saved and readable, else GET it from GitHub and save it."""
    path = raw / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    data = gh(api_path, paginate=paginate)
    dump_json(path, data)
    return data


def update_history(cfg: dict[str, Any], rows: list[dict[str, str]], save) -> None:
    """A1 for existing rows: refs pinned from the merge commit, CODEOWNERS read at base_at_merge."""
    repo = ensure_clone(cfg, blobless=True)
    todo = [r for r in rows if r["included"] == "yes"]
    print(f"fetching {len(todo)} PR heads (pull/<n>/head) into {repo}")
    fetch_pr_heads(repo, [r["pr_number"] for r in todo])
    for r in todo:
        raw = EVAL / "pool" / "raw" / cfg["name"] / r["pr_number"]
        files = cached_or_fetch(raw, "files", f"repos/{cfg['github']}/pulls/{r['pr_number']}/files")
        hist = pin(repo, r["merge_commit_sha"], r["pr_number"], files, api_base=r.get("api_base_sha", ""),
                   api_head=r.get("api_head_sha", ""), fetch=False)
        if hist["merge_strategy"] == "single_parent" and not hist["head_at_merge"]:
            hist = pin(repo, r["merge_commit_sha"], r["pr_number"], files, api_base=r.get("api_base_sha", ""),
                       api_head=r.get("api_head_sha", ""), fetch=True)
        r.update(hist)
        co_path = codeowners_at(repo, hist["base_at_merge"])[0] if hist["base_at_merge"] else None
        r["codeowners_present"] = co_path or ("no" if hist["base_at_merge"] else "unknown")
        save()
        print(f"#{r['pr_number']:<6} {hist['merge_strategy']:<14} {hist['historical_diff_status']:<13} "
              f"{hist['historical_diff_reason']}")


# categories that do not depend on approvals: no Jira key, or the requirement was edited during the PR
NOT_FROM_REVIEWS = ("no_key", "requirement_changed")


def recompute_category(row: dict[str, str], reviews: list[dict[str, Any]], co_text: str | None) -> tuple[int, str]:
    """(approvals_on_head, provisional_category) with only the approvals submitted at or before merged_at."""
    approvals = approvals_by_merge(reviews, row["merged_at"])
    on_head = approvers_on(approvals, row.get("api_head_sha", ""))
    if row["provisional_category"] in NOT_FROM_REVIEWS:
        return len(on_head), row["provisional_category"]
    root = repo_cfg(row["repo"])["analysis_root"]
    py = [f["filename"] for f in row["_files"] if f["filename"].endswith(".py") and f["filename"].startswith(root)]
    matched, user_owners, all_team = owner_info(co_text, py)
    return len(on_head), approval_category(approvals, on_head, matched, user_owners, all_team)


def update_reviews(cfg: dict[str, Any], rows: list[dict[str, str]], save) -> list[tuple[str, str, str]]:
    """A4 for existing rows. Returns (pr, old category, new category) for each row whose category changed."""
    repo = ensure_clone(cfg, blobless=True)
    changed = []
    for r in [r for r in rows if r["included"] == "yes"]:
        raw = EVAL / "pool" / "raw" / cfg["name"] / r["pr_number"]
        reviews = cached_or_fetch(raw, "reviews", f"repos/{cfg['github']}/pulls/{r['pr_number']}/reviews")
        r["_files"] = cached_or_fetch(raw, "files", f"repos/{cfg['github']}/pulls/{r['pr_number']}/files")
        base = r.get("base_at_merge") or r.get("api_base_sha", "")
        co_text = codeowners_at(repo, base)[1] if base else None
        old = r["provisional_category"]
        on_head, new = recompute_category(r, reviews, co_text)
        del r["_files"]
        r["approvals_on_head"], r["provisional_category"] = str(on_head), new
        if new != old:
            changed.append((r["pr_number"], old, new))
            print(f"#{r['pr_number']:<6} {old} -> {new}")
        save()
    print(f"{cfg['name']}: {len(changed)} included rows changed category")
    return changed


def merge_commit_locations(repo_dir: Path, row: dict[str, str], key_regex: str) -> str:
    """key_locations with "merge_commit" added for each known key in the main-branch commit's whole message.

    Older pools read only the body of that commit, but script merges (Arrow, Spark, Airflow 2019) put the key in
    its subject. Only keys already in keys_found get the location; no key is added or dropped.
    """
    locs = parse_locations(row.get("key_locations", ""))
    if row.get("merge_commit_sha"):
        msg = git(repo_dir, "log", "-1", "--format=%B", row["merge_commit_sha"], check=False)
        for k in find_keys(msg, key_regex):
            if k in locs:
                locs[k].add("merge_commit")
    return ";".join(f"{k}:{'+'.join(sorted(v))}" for k, v in sorted(locs.items()))


def update_links(cfg: dict[str, Any], rows: list[dict[str, str]]) -> None:
    """A5 for every row (no network: the local clone only): merge-commit locations, then link_status."""
    repo_dir = REPOS_DIR / cfg["name"]
    if not (repo_dir / ".git").exists():
        raise SystemExit(f"no clone in {repo_dir}; run --history first")
    for r in rows:
        if r.get("key_locations"):
            r["key_locations"] = merge_commit_locations(repo_dir, r, cfg["key_regex"])
        r["link_status"] = pool_link_status(r.get("key_locations", ""))


def update_quality(cfg: dict[str, Any], rows: list[dict[str, str]]) -> None:
    """B3 for included rows (no network): requirement_quality from eval/pool/raw/<repo>/<pr>/jira_<KEY>.json,
    the issue text saved by flag_requirement_changes.py (the same issues as eval/pool/<repo>_issues.csv)."""
    missing = 0
    for r in rows:
        if r["included"] != "yes":
            continue
        quality = {}
        for key in [k for k in r["keys_found"].split(";") if k]:
            path = EVAL / "pool" / "raw" / cfg["name"] / r["pr_number"] / f"jira_{key}.json"
            issue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            quality[key] = classify_issue(issue, r["merged_at"])
            missing += quality[key] == UNAVAILABLE
        r["requirement_quality"], r["requirement_quality_note"] = row_quality(r.get("key_locations", ""), quality)
    print(f"{cfg['name']}: requirement_quality set; {missing} key(s) with no saved issue (unavailable)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--history", action="store_true", help="A1: pin base/head/merge-base from the merge commit")
    ap.add_argument("--reviews", action="store_true", help="A4: count only approvals submitted at or before the merge")
    ap.add_argument("--links", action="store_true", help="A5: link_status from key_locations (no network)")
    ap.add_argument("--quality", action="store_true", help="B3: requirement_quality from the saved issue text")
    a = ap.parse_args(argv)
    if not (a.history or a.reviews or a.links or a.quality):
        ap.error("choose at least one update")

    cfg = repo_cfg(a.repo)
    pool = EVAL / "pool" / f"{cfg['name']}_pool.csv"
    rows = [migrate_row(r) for r in read_csv(pool)]
    if not rows:
        print(f"no rows in {pool}")
        return 1

    def save() -> None:
        write_csv(pool, rows, FIELDS)

    if a.history:
        update_history(cfg, rows, save)
    if a.reviews:
        update_reviews(cfg, rows, save)
    if a.links:
        update_links(cfg, rows)
    if a.quality:
        update_quality(cfg, rows)
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
