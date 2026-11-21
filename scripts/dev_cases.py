"""Three development cases outside the 24 scored ones (audit 21 Nov, point 5): eval/dev_cases.csv.

The dev cases are for debugging the freeze, the packets, the guide and the CodeAtlas runner. They never enter a
reported metric. They are extra PRs, one per repository, chosen after the scored draw, so the 24 stay 24.

Usage:
    python scripts/dev_cases.py --candidates                # eligible PRs, outside eval/cases.csv
    python scripts/dev_cases.py --candidates --cases %TEMP%\\trial_cases.csv   # against a trial draw
    python scripts/dev_cases.py --add airflow 6222 --reason "one key, explicit criteria, 2 Python files"
    python scripts/dev_cases.py --check                     # dev cases vs the scored cases

Eligible (all must hold, from the pool columns; no CodeAtlas output is used):
- included = yes, historical_diff_status = verified, and historical_content_status identical (or not yet
  checked, shown as such);
- link_status = verified and exactly one Jira key;
- requirement_quality explicit_criteria or descriptive_issue;
- jira_history not created_text_only (its edit history must be known);
- a manageable change: at most 5 Python files and 10 files in all;
- not a scored case, no Jira key shared with a scored case, no case group shared with a scored case.

--add writes the row (set "dev", ID AF-D01 / AR-D01 / SP-D01 ...) into eval/dev_cases.csv, which has the same
columns as eval/cases.csv, and refuses a PR that fails the checks. Freeze them with
    python scripts/freeze_case.py --all --cases eval/dev_cases.csv       (into eval/dev_cases/)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from case_groups import group_of, keys_of, load_groups
from common import EVAL, load_repos, read_csv, write_csv

DEV_FILE = EVAL / "dev_cases.csv"
GOOD_QUALITY = ("explicit_criteria", "descriptive_issue")
MAX_PY_FILES = 5
MAX_FILES = 10


def case_fields() -> list[str]:
    return (EVAL / "cases.csv").read_text(encoding="utf-8").splitlines()[0].split(",")


def pool_rows(repo: str, pool_dir: Path) -> list[dict[str, str]]:
    return [dict(r, repo=r.get("repo") or repo) for r in read_csv(pool_dir / f"{repo}_pool.csv")]


def problems(row: dict[str, str], scored: list[dict[str, str]], groups: dict[tuple[str, str], str]) -> list[str]:
    """Why a pool row cannot be a dev case ([] = eligible)."""
    out = []
    if row.get("included") != "yes":
        out.append("not included in the pool")
    if row.get("historical_diff_status") != "verified":
        out.append(f"historical_diff_status {row.get('historical_diff_status') or '(none)'}")
    if row.get("historical_content_status") == "differs":
        out.append("historical_content_status differs")
    keys = keys_of(row)
    if len(keys) != 1:
        out.append(f"{len(keys)} Jira keys (one wanted)")
    if row.get("link_status") != "verified":
        out.append(f"link_status {row.get('link_status') or '(none)'}")
    if row.get("requirement_quality") not in GOOD_QUALITY:
        out.append(f"requirement_quality {row.get('requirement_quality') or '(none)'}")
    if "created_text_only" in (row.get("jira_history") or ""):
        out.append("Jira edit history unknown (created_text_only)")
    if int(row.get("py_files_changed") or 0) > MAX_PY_FILES or int(row.get("files_changed") or 0) > MAX_FILES:
        out.append(f"too large ({row.get('py_files_changed')} Python files, {row.get('files_changed')} in all)")
    out += overlap(row, scored, groups)
    return out


def overlap(row: dict[str, str], scored: list[dict[str, str]], groups: dict[tuple[str, str], str]) -> list[str]:
    """Ways a row overlaps the scored cases: same PR, a shared Jira key, a shared case group."""
    out = []
    repo, pr = row["repo"], str(row["pr_number"])
    if any(s["repo"] == repo and str(s["pr_number"]) == pr for s in scored):
        out.append("it is a scored case")
    shared = sorted(keys_of(row) & {k for s in scored for k in keys_of(s)})
    if shared:
        out.append(f"Jira key shared with a scored case: {', '.join(shared)}")
    gid = group_of(groups, repo, pr)
    if gid and any(group_of(groups, s["repo"], s["pr_number"]) == gid for s in scored):
        out.append(f"case group {gid} shared with a scored case")
    return out


def candidates(repos: list[str], scored: list[dict[str, str]], pool_dir: Path,
               groups: dict[tuple[str, str], str]) -> dict[str, list[dict[str, str]]]:
    """Eligible rows per repo, explicit criteria first, then the smallest change, then PR number."""
    out = {}
    for repo in repos:
        rows = [r for r in pool_rows(repo, pool_dir) if not problems(r, scored, groups)]
        out[repo] = sorted(rows, key=lambda r: (r["requirement_quality"] != "explicit_criteria",
                                                int(r.get("files_changed") or 0), int(r["pr_number"])))
    return out


def dev_row(pool_row: dict[str, str], case_id: str, cfg: dict[str, str], reason: str) -> dict[str, str]:
    return {
        "case_id": case_id, "set": "dev", "repo": pool_row["repo"], "pr_number": pool_row["pr_number"],
        "pr_url": pool_row["pr_url"], "category_provisional": pool_row["provisional_category"],
        "decision_cutoff_utc": pool_row["merged_at"],
        "base_sha": pool_row.get("base_at_merge") or pool_row.get("api_base_sha", ""),
        "head_sha": pool_row.get("head_at_merge") or pool_row.get("api_head_sha", ""),
        "merge_base_sha": pool_row.get("merge_base_sha", ""), "jira_keys": pool_row["keys_found"],
        "policy_file": f"eval/policies/{pool_row['repo']}.yaml", "analysis_root": cfg["analysis_root"],
        "source_dir": f"eval/dev_cases/{case_id}/sources", "notes": f"dev case: {reason}",
    }


def next_id(prefix: str, rows: list[dict[str, str]]) -> str:
    used = {r["case_id"] for r in rows}
    n = 1
    while f"{prefix}-D{n:02d}" in used:
        n += 1
    return f"{prefix}-D{n:02d}"


def check(dev: list[dict[str, str]], scored: list[dict[str, str]], groups: dict[tuple[str, str], str],
          repos: list[str]) -> list[str]:
    """Every reason the dev set is not usable ([] = fine)."""
    out = []
    for r in dev:
        if r.get("set") != "dev":
            out.append(f"{r['case_id']}: set is {r.get('set')!r}, not 'dev'")
        out += [f"{r['case_id']}: {p}" for p in overlap(r, scored, groups)]
    seen: dict[str, str] = {}
    for r in dev:
        for k in keys_of(r):
            if k in seen:
                out.append(f"{r['case_id']}: Jira key {k} also in {seen[k]}")
            seen[k] = r["case_id"]
    for repo in repos:
        n = sum(r["repo"] == repo for r in dev)
        if n != 1:
            out.append(f"{repo}: {n} dev cases (one per repository wanted)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--candidates", action="store_true")
    g.add_argument("--add", nargs=2, metavar=("REPO", "PR"))
    g.add_argument("--check", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--cases", type=Path, default=EVAL / "cases.csv", help="the scored cases (default eval/cases.csv)")
    ap.add_argument("--dev", type=Path, default=DEV_FILE)
    ap.add_argument("--pool-dir", type=Path, default=EVAL / "pool")
    ap.add_argument("--repos", nargs="+", default=["airflow", "arrow", "spark"])
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args(argv)

    cfgs = load_repos()
    groups = load_groups()
    scored = [r for r in read_csv(a.cases) if r.get("case_id")]
    if not scored:
        print(f"note: {a.cases} has no cases yet, so overlap with the scored draw is not checked")
    dev = [r for r in read_csv(a.dev) if r.get("case_id")]

    if a.candidates:
        for repo, rows in candidates(a.repos, scored, a.pool_dir, groups).items():
            print(f"\n{repo}: {len(rows)} eligible")
            for r in rows[:a.top]:
                content = r.get("historical_content_status") or "content not checked"
                print(f"  #{r['pr_number']:<6} {r['keys_found']:<14} {r['requirement_quality']:<18} "
                      f"{r['py_files_changed']} py / {r['files_changed']} files  {content}  {r['title'][:60]}")
        return 0

    if a.add:
        repo, pr = a.add
        rows = [r for r in pool_rows(repo, a.pool_dir) if r["pr_number"] == pr]
        if not rows:
            raise SystemExit(f"#{pr} is not in eval/pool/{repo}_pool.csv")
        why = problems(rows[0], scored, groups) + overlap(rows[0], dev, groups)
        if why:
            raise SystemExit(f"{repo} #{pr} cannot be a dev case: " + "; ".join(why))
        if not a.reason:
            raise SystemExit("give --reason: why this PR was chosen (recorded in the notes column)")
        row = dev_row(rows[0], next_id(cfgs[repo]["case_prefix"], dev), cfgs[repo], a.reason)
        write_csv(a.dev, [*dev, row], case_fields())
        print(f"{row['case_id']}: {repo} #{pr} added to {a.dev}")
        return 0

    issues = check(dev, scored, groups, a.repos)
    for line in issues:
        print(f"  - {line}")
    print(f"{len(dev)} dev cases; {'OK' if not issues else f'{len(issues)} problem(s)'}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
