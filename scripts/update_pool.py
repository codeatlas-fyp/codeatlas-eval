"""Bring an already-built pool up to the integrity fixes without rebuilding it.

Usage:
    python scripts/update_pool.py --repo airflow --history    # A1: pin refs from the merge commit (clone + PR files)

Only included rows are touched; excluded rows keep what they have. GitHub is read with GET only and every answer
is cached in eval/pool/raw/<repo>/<pr>/ (git-ignored), so a rerun reads the cache. The pool is written after
every row, so a crash loses nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_pool import FIELDS, migrate_row
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--history", action="store_true", help="A1: pin base/head/merge-base from the merge commit")
    a = ap.parse_args(argv)
    if not a.history:
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
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
