"""Freeze the evidence for sampled cases (build plan C5 step 3).

Usage:
    python scripts/freeze_case.py --case AF-01
    python scripts/freeze_case.py --all

For each case creates eval/cases/<id>/ with case.yaml, sources/ (PR, commits, reviews, files, Jira issues with
changelog, CODEOWNERS_at_base.txt, fetched_at.txt), an empty checklist.csv and blank label files.
Existing sources are never overwritten unless --refresh. Nothing is written to GitHub or Jira.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone

from common import (EVAL, codeowners_at, dump_json, ensure_clone, gh, git, jira_issue, read_csv, repo_cfg, write_csv)

TEMPLATES = EVAL / "templates"


def freeze(row: dict[str, str], refresh: bool) -> None:
    cid = row["case_id"]
    cfg = repo_cfg(row["repo"])
    case_dir = EVAL / ("challenge" if row["set"] == "challenge" else "cases") / cid
    src = case_dir / "sources"
    if src.exists() and any(src.iterdir()) and not refresh:
        print(f"{cid}: sources already frozen, skipping (use --refresh to re-fetch)")
        return
    repo = ensure_clone(cfg)
    n = row["pr_number"]
    pr = gh(f"repos/{cfg['github']}/pulls/{n}")
    data = {"pr": pr,
            "commits": gh(f"repos/{cfg['github']}/pulls/{n}/commits", paginate=True),
            "reviews": gh(f"repos/{cfg['github']}/pulls/{n}/reviews", paginate=True),
            "files": gh(f"repos/{cfg['github']}/pulls/{n}/files", paginate=True)}
    for name, d in data.items():
        dump_json(src / f"{name}.json", d)
    keys = [k for k in row["jira_keys"].split(";") if k]
    for k in keys:
        try:
            dump_json(src / f"jira_{k}.json", jira_issue(cfg["jira_base"], k))
        except Exception as e:  # noqa: BLE001
            (src / f"jira_{k}.INACCESSIBLE.txt").write_text(f"{e}\n", encoding="utf-8")

    base, head = pr["base"]["sha"], pr["head"]["sha"]
    git(repo, "fetch", "--quiet", "origin", f"pull/{n}/head:refs/pr/{n}", check=False)
    merge_base = git(repo, "merge-base", base, head, check=False).strip()
    co_path, co_text = codeowners_at(repo, base)
    (src / "CODEOWNERS_at_base.txt").write_text(co_text if co_text is not None else "NO CODEOWNERS FILE AT BASE\n", encoding="utf-8")
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (src / "fetched_at.txt").write_text(fetched + "\n", encoding="utf-8")

    cutoff = pr.get("merged_at") or row["decision_cutoff_utc"]
    (case_dir / "case.yaml").write_text(
        (TEMPLATES / "case.yaml").read_text(encoding="utf-8").format(
            case_id=cid, set=row["set"], repo=cfg["github"], pr_number=n, pr_url=pr["html_url"], cutoff=cutoff,
            base_sha=base, head_sha=head, merge_base_sha=merge_base or "unknown",
            jira_keys=", ".join(keys) or "none", policy_file=f"eval/policies/{cfg['name']}.yaml",
            analysis_root=cfg["analysis_root"] or "/", codeowners=co_path or "none", fetched_at=fetched,
            category=row["category_provisional"]),
        encoding="utf-8")
    for t in ("checklist.csv", "label_A.yaml", "label_B.yaml", "adjudicated.yaml"):
        dest = case_dir / t
        if not dest.exists():
            src_t = TEMPLATES / ("label.yaml" if t.startswith("label_") else t)
            shutil.copy(src_t, dest)
    (case_dir / "run").mkdir(exist_ok=True)
    (case_dir / "run" / ".gitkeep").touch()

    row.update({"decision_cutoff_utc": cutoff, "base_sha": base, "head_sha": head, "merge_base_sha": merge_base,
                "policy_file": f"eval/policies/{cfg['name']}.yaml"})
    print(f"{cid}: frozen #{n} ({len(data['files'])} files, {len(data['reviews'])} reviews, keys {keys or 'none'})")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--case")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    path = EVAL / "cases.csv"
    fields = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    rows = read_csv(path)
    todo = rows if a.all else [r for r in rows if r["case_id"] == a.case]
    if not todo:
        raise SystemExit(f"case {a.case} not in eval/cases.csv")
    for r in todo:
        freeze(r, a.refresh)
        write_csv(path, rows, fields)


if __name__ == "__main__":
    main()
