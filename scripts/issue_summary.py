"""List the Jira issue behind every included pool row, with how much text it has (build plan C4 support).

Usage:
    python scripts/issue_summary.py --repo airflow

Run after flag_requirement_changes.py (or build_pool.py --jira), which saved each issue in
eval/pool/raw/<repo>/<pr>/jira_<KEY>.json. Writes eval/pool/<repo>_issues.csv with one row per PR and key:
summary, description length in characters and lines, and where the text came from. Many 2019 Airflow
issues have a title only; a semantic case needs criteria to match, so this file lets the team see that before
sampling. It reads only the issue text, never CodeAtlas output.
"""

from __future__ import annotations

import argparse
import json

from common import EVAL, read_csv, repo_cfg, write_csv

FIELDS = ["repo", "pr_number", "key", "summary", "description_chars", "description_lines", "title_only",
          "provisional_category", "source"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    a = ap.parse_args(argv)

    cfg = repo_cfg(a.repo)
    rows = read_csv(EVAL / "pool" / f"{cfg['name']}_pool.csv")
    raw_root = EVAL / "pool" / "raw" / cfg["name"]
    out, missing = [], 0
    for row in rows:
        if row["included"] != "yes":
            continue
        for key in [k for k in row["keys_found"].split(";") if k]:
            path = raw_root / row["pr_number"] / f"jira_{key}.json"
            if not path.exists():
                missing += 1
                continue
            issue = json.loads(path.read_text(encoding="utf-8"))
            description = (issue.get("fields", {}).get("description") or "").strip()
            out.append({
                "repo": cfg["name"], "pr_number": row["pr_number"], "key": key,
                "summary": issue.get("fields", {}).get("summary", ""),
                "description_chars": len(description),
                "description_lines": len([ln for ln in description.splitlines() if ln.strip()]),
                "title_only": "yes" if not description else "no",
                "provisional_category": row["provisional_category"],
                "source": issue.get("archive", {}).get("list") or "jira",
            })
    dest = EVAL / "pool" / f"{cfg['name']}_issues.csv"
    write_csv(dest, out, FIELDS)
    title_only = sum(r["title_only"] == "yes" for r in out)
    print(f"{len(out)} issues in {dest}: {title_only} title only, {len(out) - title_only} with a description")
    if missing:
        print(f"{missing} keys have no saved issue yet; run flag_requirement_changes.py --repo {cfg['name']} first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
