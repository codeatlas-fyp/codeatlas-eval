"""Bring an already-built pool up to the integrity fixes without rebuilding it.

Usage:
    python scripts/update_pool.py --repo airflow --history    # A1: pin refs from the merge commit (clone + PR files)
    python scripts/update_pool.py --repo airflow --reviews    # A4: approvals at or before the merge (reviews endpoint)

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
from common import EVAL, codeowners_at, dump_json, ensure_clone, gh, read_csv, repo_cfg, write_csv
from history import fetch_pr_heads, pin


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--history", action="store_true", help="A1: pin base/head/merge-base from the merge commit")
    ap.add_argument("--reviews", action="store_true", help="A4: count only approvals submitted at or before the merge")
    a = ap.parse_args(argv)
    if not (a.history or a.reviews):
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
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
