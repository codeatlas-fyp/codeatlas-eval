"""Mark pool rows whose Jira summary or description was edited while the PR was being worked on.

Usage:
    python scripts/flag_requirement_changes.py --repo airflow
    python scripts/flag_requirement_changes.py --repo arrow --limit 50     # resumable

For pools built without --jira (or while Apache Jira refused anonymous reads). For every included row with a
Jira key, it reads the issue (Jira, or the public mailing-list archive when Jira needs a login), and if the
summary or description changed after the PR's first commit and before its merge, sets
provisional_category to requirement_changed, exactly as build_pool.py --jira would have. The first-commit time
comes from the cached eval/pool/raw/<repo>/<pr>/commits.json written by build_pool.py on this machine.
Rows already checked are listed in eval/pool/raw/<repo>/requirement_checked.txt and skipped next time.
"""

from __future__ import annotations

import argparse
import json

from build_pool import FIELDS, migrate_row, requirement_edited
from common import EVAL, read_csv, repo_cfg, write_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    cfg = repo_cfg(a.repo)
    pool = EVAL / "pool" / f"{cfg['name']}_pool.csv"
    rows = [migrate_row(r) for r in read_csv(pool)]
    if not rows:
        print(f"no rows in {pool}; run build_pool.py first")
        return 1
    raw_root = EVAL / "pool" / "raw" / cfg["name"]
    done_file = raw_root / "requirement_checked.txt"
    done = set(done_file.read_text(encoding="utf-8").split()) if done_file.exists() else set()
    checked = changed = unknown = 0

    for row in rows:
        n = row["pr_number"]
        keys = [k for k in row["keys_found"].split(";") if k]
        if row["included"] != "yes" or not keys or n in done:
            continue
        if a.limit and checked >= a.limit:
            break
        raw = raw_root / n
        commits_file = raw / "commits.json"
        if not commits_file.exists():
            print(f"#{n:<6} no cached commits.json (built on another machine?); skipped")
            continue
        commits = json.loads(commits_file.read_text(encoding="utf-8"))
        began = commits[0]["commit"]["committer"]["date"] if commits else row["merged_at"]
        edited = requirement_edited(cfg, keys, began, row["merged_at"], raw)
        checked += 1
        if edited is None:
            unknown += 1
            print(f"#{n:<6} {';'.join(keys)}: issue not readable, category kept ({row['provisional_category']})")
        else:
            if edited:
                changed += 1
                print(f"#{n:<6} {';'.join(keys)}: edited during the PR -> requirement_changed "
                      f"(was {row['provisional_category']})")
                row["provisional_category"] = "requirement_changed"
            else:
                print(f"#{n:<6} {';'.join(keys)}: unchanged")
            done.add(n)
            write_csv(pool, rows, FIELDS)
            done_file.parent.mkdir(parents=True, exist_ok=True)
            done_file.write_text("\n".join(sorted(done, key=int)) + "\n", encoding="utf-8")

    print(f"\nchecked {checked} rows: {changed} now requirement_changed, {unknown} unreadable. Pool: {pool}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
