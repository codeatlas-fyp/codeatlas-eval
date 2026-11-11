"""Seeded sampling of pilot cases from the pool files (build plan C4, C5 step 2).

Usage:
    python scripts/sample_cases.py                         # airflow, arrow, libcloud; seed 20261114
    python scripts/sample_cases.py --repos airflow arrow spark

Draws included pool rows per category up to the targets (rarest category first), at most 8 per repo,
assigns case IDs (AF-01, AR-01, LC-01 ...) in merge order, and writes eval/cases.csv plus
eval/results/sampling_report.md. Shortfalls are reported, never filled by bending the rules.
Refuses to overwrite an existing eval/cases.csv unless --force.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from datetime import date

from common import EVAL, load_repos, read_csv, write_csv

TARGETS = {  # build plan C4; total 24
    "requirement_changed": 2,
    "no_key": 2,
    "semantic_no_match": 4,
    "meaningful_link": 5,
    "ownership_gap": 5,
    "supported_approval": 6,
}
PER_REPO = 8
CASE_FIELDS = (EVAL / "cases.csv").read_text(encoding="utf-8").splitlines()[0].split(",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", default=["airflow", "arrow", "libcloud"])
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    existing = [r for r in read_csv(EVAL / "cases.csv") if r.get("case_id")]
    if existing and not a.force:
        raise SystemExit("eval/cases.csv already has cases; use --force only before any evidence is frozen")

    cfgs = load_repos()
    rng = random.Random(a.seed)
    pools = {r: [x for x in read_csv(EVAL / "pool" / f"{r}_pool.csv") if x["included"] == "yes"] for r in a.repos}
    taken: dict[str, list[dict[str, str]]] = defaultdict(list)
    shortfalls = []

    for cat, target in TARGETS.items():
        by_repo = {r: sorted([x for x in pools[r] if x["provisional_category"] == cat], key=lambda x: int(x["pr_number"])) for r in a.repos}
        for r in by_repo:
            rng.shuffle(by_repo[r])
        got, order = 0, list(a.repos)
        while got < target and any(by_repo[r] for r in order):
            for r in order:
                if got >= target:
                    break
                if by_repo[r] and len(taken[r]) < PER_REPO:
                    taken[r].append(by_repo[r].pop())
                    got += 1
            if all(len(taken[r]) >= PER_REPO or not by_repo[r] for r in order):
                break
        if got < target:
            shortfalls.append(f"{cat}: {got} of {target}")

    cases = []
    for r in a.repos:
        prefix = cfgs[r]["case_prefix"]
        for i, x in enumerate(sorted(taken[r], key=lambda x: x["merged_at"]), start=1):
            cases.append({
                "case_id": f"{prefix}-{i:02d}", "set": "pilot", "repo": r, "pr_number": x["pr_number"], "pr_url": x["pr_url"],
                "category_provisional": x["provisional_category"], "decision_cutoff_utc": x["merged_at"],
                "base_sha": x["base_sha"], "head_sha": x["head_sha"], "jira_keys": x["keys_found"],
                "analysis_root": cfgs[r]["analysis_root"], "source_dir": f"eval/cases/{prefix}-{i:02d}/sources",
            })
    write_csv(EVAL / "cases.csv", cases, CASE_FIELDS)

    counts = Counter((c["repo"], c["category_provisional"]) for c in cases)
    lines = [f"# Sampling report", "", f"Run on {date.today().isoformat()}; seed {a.seed}; repos {', '.join(a.repos)}.", "",
             "| Repo | " + " | ".join(TARGETS) + " | Total |", "|---" * (len(TARGETS) + 2) + "|"]
    for r in a.repos:
        lines.append(f"| {r} | " + " | ".join(str(counts[(r, c)]) for c in TARGETS) + f" | {len(taken[r])} |")
    lines += ["", f"Total cases: {len(cases)} of 24.", "", "Shortfalls: " + ("; ".join(shortfalls) if shortfalls else "none")]
    (EVAL / "results").mkdir(exist_ok=True)
    (EVAL / "results" / "sampling_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
