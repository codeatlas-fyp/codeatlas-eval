"""Seeded sampling of pilot cases from the pool files (build plan C4, C5 step 2; Part C of the integrity fixes).

Usage:
    python scripts/sample_cases.py                                   # airflow, arrow, spark; seed 20261114
    python scripts/sample_cases.py --cases %TEMP%\\cases.csv --report %TEMP%\\report.md   # try it outside the repo

1. Allocation. QUOTAS gives the cases per category (24 in all) and PER_REPO the cases per repo (8). A
   deterministic backtracking search over the repo x category count matrix finds counts that meet every quota
   and every repo total when the pool allows it (each cell at most the included rows in that cell). When it does
   not, it returns the allocation with the most cases (exact, via max-flow) and the report lists every shortfall
   with its reason. The pool is never silently underfilled and the rules are never bent.
2. Choice inside each cell: seeded random (seed 20261114), after a fixed preference order: link_status verified
   first, then requirement_quality explicit_criteria / descriptive_issue over title_only, then
   historical_diff_status verified over unverifiable.
3. Case IDs (AF-01, AR-01, SP-01 ...) in merge order. Writes the cases file and the report; refuses to overwrite a
   cases file that already has cases unless --force. The report records the seed and the sha256 of each pool file
   (not the date), so the same pools and seed give the same report.
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any

from common import EVAL, load_repos, read_csv, write_csv

# proposed, pending team approval (20 Nov 2026)
QUOTAS = {
    "supported_approval": 7,
    "ownership_gap": 6,
    "no_approval": 7,
    "requirement_changed": 2,
    "no_key": 2,
}
PER_REPO = 8
SEED = 20261114
DEFAULT_REPOS = ["airflow", "arrow", "spark"]
LINK_RANK = {"verified": 0, "title_unchecked": 1, "uncertain": 2}
QUALITY_RANK = {"explicit_criteria": 0, "descriptive_issue": 0, "title_only": 1}
HIST_RANK = {"verified": 0}


def _case_fields() -> list[str]:
    return (EVAL / "cases.csv").read_text(encoding="utf-8").splitlines()[0].split(",")


# ---------------------------------------------------------------- allocation


def max_total(avail: dict[str, dict[str, int]], repos: list[str], cats: list[str], quotas: dict[str, int],
              per_repo: int) -> int:
    """Most cases any allocation can reach: max-flow source -> category (quota) -> repo (cell) -> sink (per_repo)."""
    nodes = ["s", *cats, *repos, "t"]
    cap: dict[tuple[str, str], int] = {}
    for c in cats:
        cap[("s", c)] = quotas[c]
        for r in repos:
            cap[(c, r)] = avail[r][c]
    for r in repos:
        cap[(r, "t")] = per_repo
    for (a, b) in list(cap):
        cap.setdefault((b, a), 0)
    flow = 0
    while True:
        parent = {"s": None}
        queue = ["s"]
        while queue and "t" not in parent:
            u = queue.pop(0)
            for v in nodes:
                if v not in parent and cap.get((u, v), 0) > 0:
                    parent[v] = u
                    queue.append(v)
        if "t" not in parent:
            return flow
        path, v = [], "t"
        while parent[v] is not None:
            path.append((parent[v], v))
            v = parent[v]
        push = min(cap[e] for e in path)
        for a, b in path:
            cap[(a, b)] -= push
            cap[(b, a)] += push
        flow += push


def _splits(total: int, limits: list[int]) -> list[tuple[int, ...]]:
    """Every way to split `total` over the repos within their limits, most even first (deterministic)."""
    out = [s for s in product(*(range(min(total, lim) + 1) for lim in limits)) if sum(s) == total]
    return sorted(out, key=lambda s: (max(s) - min(s), [-x for x in s]))


def allocate(avail: dict[str, dict[str, int]], repos: list[str], quotas: dict[str, int] = QUOTAS,
             per_repo: int = PER_REPO) -> dict[str, dict[str, int]]:
    """Counts per repo and category: meets every quota and repo total when feasible, else the most cases.

    Backtracking over the categories (in QUOTAS order); each step tries every split of the category's count over
    the repos. The target is the exact maximum from max_total, so the first allocation found is optimal; the
    order of the tries makes the result deterministic.
    """
    cats = list(quotas)
    target = max_total(avail, repos, cats, quotas, per_repo)

    def bound(i: int, room: dict[str, int]) -> int:
        return min(sum(room.values()), sum(min(quotas[c], sum(min(avail[r][c], room[r]) for r in repos))
                                         for c in cats[i:]))

    def rec(i: int, room: dict[str, int], got: int) -> list[tuple[int, ...]] | None:
        if got == target:
            return [tuple(0 for _ in repos)] * (len(cats) - i)
        if i == len(cats) or got + bound(i, room) < target:
            return None
        c = cats[i]
        limits = [min(avail[r][c], room[r]) for r in repos]
        most = min(quotas[c], sum(limits))
        for n in range(most, -1, -1):           # fill the category as far as possible first
            for split in _splits(n, limits):
                rest = rec(i + 1, {r: room[r] - k for r, k in zip(repos, split)}, got + n)
                if rest is not None:
                    return [split, *rest]
        return None

    found = rec(0, {r: per_repo for r in repos}, 0)
    assert found is not None, "max-flow target must be reachable"
    return {r: {c: found[j][k] for j, c in enumerate(cats)} for k, r in enumerate(repos)}


def shortfalls(avail: dict[str, dict[str, int]], alloc: dict[str, dict[str, int]], repos: list[str],
               quotas: dict[str, int] = QUOTAS, per_repo: int = PER_REPO) -> list[dict[str, Any]]:
    """One row per category below its quota and per repo below PER_REPO, with the reason."""
    rows = []
    for c, q in quotas.items():
        got = sum(alloc[r][c] for r in repos)
        if got < q:
            have = {r: avail[r][c] for r in repos}
            if sum(have.values()) < q:
                why = f"only {sum(have.values())} included pool rows in this category ({_fmt(have)})"
            else:
                full = [r for r in repos if have[r] > alloc[r][c]]
                why = (f"{sum(have.values())} rows exist ({_fmt(have)}), but the repos that have more "
                       f"({', '.join(full)}) are already at {per_repo} cases")
            rows.append({"what": c, "target": q, "got": got, "reason": why})
    for r in repos:
        got = sum(alloc[r].values())
        if got < per_repo:
            open_rows = {c: avail[r][c] - alloc[r][c] for c in quotas if avail[r][c] > alloc[r][c]}
            why = (f"no more rows in categories with quota left (unused rows only in full categories: "
                   f"{_fmt(open_rows) or 'none'})")
            rows.append({"what": r, "target": per_repo, "got": got, "reason": why})
    return rows


def _fmt(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items() if v)


# ---------------------------------------------------------------- choice inside a cell


def preference(row: dict[str, str]) -> tuple[int, int, int]:
    return (LINK_RANK.get(row.get("link_status", ""), 3), QUALITY_RANK.get(row.get("requirement_quality", ""), 2),
            HIST_RANK.get(row.get("historical_diff_status", ""), 1))


def choose(pools: dict[str, list[dict[str, str]]], alloc: dict[str, dict[str, int]], repos: list[str],
           seed: int = SEED) -> dict[str, list[dict[str, str]]]:
    """The PRs of each cell: preference order first, seeded random order among equals."""
    rng = random.Random(seed)
    taken: dict[str, list[dict[str, str]]] = {r: [] for r in repos}
    for r in repos:
        for c in QUOTAS:
            cell = sorted((x for x in pools[r] if x["provisional_category"] == c), key=lambda x: int(x["pr_number"]))
            keyed = [(preference(x), rng.random(), x) for x in cell]
            taken[r] += [x for _, _, x in sorted(keyed, key=lambda t: (t[0], t[1]))[:alloc[r].get(c, 0)]]
    return taken


# ---------------------------------------------------------------- output


def case_rows(taken: dict[str, list[dict[str, str]]], repos: list[str], cfgs: dict[str, Any]) -> list[dict[str, str]]:
    cases = []
    for r in repos:
        prefix = cfgs[r]["case_prefix"]
        for i, x in enumerate(sorted(taken[r], key=lambda x: x["merged_at"]), start=1):
            cid = f"{prefix}-{i:02d}"
            cases.append({
                "case_id": cid, "set": "pilot", "repo": r, "pr_number": x["pr_number"], "pr_url": x["pr_url"],
                "category_provisional": x["provisional_category"], "decision_cutoff_utc": x["merged_at"],
                "base_sha": x.get("base_at_merge") or x.get("api_base_sha", ""),
                "head_sha": x.get("head_at_merge") or x.get("api_head_sha", ""),
                "merge_base_sha": x.get("merge_base_sha", ""), "jira_keys": x["keys_found"],
                "policy_file": f"eval/policies/{r}.yaml", "analysis_root": cfgs[r]["analysis_root"],
                "source_dir": f"eval/cases/{cid}/sources",
            })
    return cases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_keys(row: dict[str, str]) -> int:
    from links import VERIFIED, parse_locations, pool_key_status
    return sum(pool_key_status(v) == VERIFIED for v in parse_locations(row.get("key_locations", "")).values())


def report(seed: int, repos: list[str], pool_files: dict[str, Path], avail, alloc, short, taken) -> list[str]:
    cats = list(QUOTAS)
    total = sum(sum(a.values()) for a in alloc.values())
    out = ["# Sampling report", "", f"Seed {seed}; repos {', '.join(repos)}.", "", "Pool files:", ""]
    out += [f"- `{p.relative_to(EVAL.parent).as_posix() if p.is_relative_to(EVAL.parent) else p}` sha256 `{sha256(p)}`"
            for p in pool_files.values()]
    out += ["", f"## Quotas (proposed, pending team approval): {sum(QUOTAS.values())} cases, {PER_REPO} per repo", "",
            "| Category | Quota |", "|---|---|"] + [f"| {c} | {q} |" for c, q in QUOTAS.items()]
    out += ["", "## Included pool rows per cell", "", "| Repo | " + " | ".join(cats) + " |", "|---" * (len(cats) + 1) + "|"]
    out += [f"| {r} | " + " | ".join(str(avail[r][c]) for c in cats) + " |" for r in repos]
    out += ["", "## Allocation", "", "| Repo | " + " | ".join(cats) + " | Total |", "|---" * (len(cats) + 2) + "|"]
    out += [f"| {r} | " + " | ".join(str(alloc[r][c]) for c in cats) + f" | {sum(alloc[r].values())} |" for r in repos]
    out += [f"| total | " + " | ".join(str(sum(alloc[r][c] for r in repos)) for c in cats) + f" | {total} |"]
    out += ["", f"Total cases: {total} of {sum(QUOTAS.values())}.", "", "## Shortfalls", ""]
    if short:
        out += ["| Category or repo | Target | Got | Reason |", "|---|---|---|---|"]
        out += [f"| {s['what']} | {s['target']} | {s['got']} | {s['reason']} |" for s in short]
    else:
        out += ["None: every quota and every repo total is met."]
    picked = [x for r in repos for x in taken[r]]
    for title, field in (("Requirement quality", "requirement_quality"), ("Link status", "link_status"),
                         ("Historical diff status", "historical_diff_status")):
        mix = Counter(x.get(field) or "(none)" for x in picked)
        out += ["", f"## {title} of the sampled cases", "", "| Value | Cases |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in sorted(mix.items())]
    out += ["", "## Jira keys per repo (sampled cases)", "",
            "| Repo | One key | Several keys | At least one verified key |", "|---|---|---|---|"]
    for r in repos:
        nkeys = [len([k for k in x["keys_found"].split(";") if k]) for x in taken[r]]
        out.append(f"| {r} | {sum(n == 1 for n in nkeys)} | {sum(n > 1 for n in nkeys)} | "
                   f"{sum(verified_keys(x) > 0 for x in taken[r])} |")
    # a key whose archive has only its Created email (created_text_only) has an unknown edit history: the row
    # cannot be proven unchanged, so its category (anything but requirement_changed) is reported separately
    from scoring import history_unknown
    out += ["", "## Requirement not proven unchanged (edit history unknown)", "",
            "Rows with a created_text_only key: C1 and C6 stay INSUFFICIENT_EVIDENCE for them "
            "(eval/scoring_rules.md), and their category cannot be proven to be 'unchanged'.", "",
            "| Repo | Sampled cases | Cases |", "|---|---|---|"]
    for r in repos:
        unknown = [x for x in taken[r] if history_unknown(x.get("jira_history", ""))]
        out.append(f"| {r} | {len(unknown)} | "
                   f"{', '.join('#' + x['pr_number'] + ' ' + x['provisional_category'] for x in unknown) or '-'} |")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", default=DEFAULT_REPOS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--pool-dir", type=Path, default=EVAL / "pool")
    ap.add_argument("--cases", type=Path, default=EVAL / "cases.csv")
    ap.add_argument("--report", type=Path, default=EVAL / "results" / "sampling_report.md")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    if [r for r in read_csv(a.cases) if r.get("case_id")] and not a.force:
        raise SystemExit(f"{a.cases} already has cases; use --force only before any evidence is frozen")
    cfgs = load_repos()
    pool_files = {r: a.pool_dir / f"{r}_pool.csv" for r in a.repos}
    pools = {r: [x for x in read_csv(p) if x["included"] == "yes"] for r, p in pool_files.items()}
    avail = {r: {c: sum(x["provisional_category"] == c for x in pools[r]) for c in QUOTAS} for r in a.repos}
    alloc = allocate(avail, a.repos)
    short = shortfalls(avail, alloc, a.repos)
    taken = choose(pools, alloc, a.repos, a.seed)
    write_csv(a.cases, case_rows(taken, a.repos, cfgs), _case_fields())
    lines = report(a.seed, a.repos, pool_files, avail, alloc, short, taken)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
