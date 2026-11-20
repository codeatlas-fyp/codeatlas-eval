"""Tests for scripts/sample_cases.py (Part C; standard library only, synthetic pools, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sample_cases as sc
from common import read_csv, write_csv

REPOS = ["airflow", "arrow", "spark"]
# the old greedy (category by category, round robin over repos) reaches 18 here; 24 is feasible
HARD = {"airflow": {"supported_approval": 8, "ownership_gap": 8, "no_approval": 8, "requirement_changed": 2, "no_key": 0},
        "arrow": {"supported_approval": 0, "ownership_gap": 5, "no_approval": 0, "requirement_changed": 8, "no_key": 2},
        "spark": {"supported_approval": 8, "ownership_gap": 0, "no_approval": 0, "requirement_changed": 0, "no_key": 1}}


def old_greedy_total(avail):
    """The allocation the sampler used before Part C, counts only."""
    taken = {r: 0 for r in REPOS}
    total = 0
    for c, target in sc.QUOTAS.items():
        left = dict((r, avail[r][c]) for r in REPOS)
        got = 0
        while got < target and any(left.values()):
            for r in REPOS:
                if got >= target:
                    break
                if left[r] and taken[r] < sc.PER_REPO:
                    taken[r] += 1
                    left[r] -= 1
                    got += 1
            if all(taken[r] >= sc.PER_REPO or not left[r] for r in REPOS):
                break
        total += got
    return total


def pool_rows(repo, avail, start=1000):
    rows, n = [], start
    for c, k in avail.items():
        for _ in range(k):
            n += 1
            rows.append({"repo": repo, "pr_number": str(n), "pr_url": f"u/{n}", "merged_at": f"2022-04-01T00:{n % 60:02d}:00Z",
                         "provisional_category": c, "included": "yes", "keys_found": "" if c == "no_key" else f"K-{n}",
                         "key_locations": "" if c == "no_key" else f"K-{n}:commit", "link_status": "verified",
                         "requirement_quality": "descriptive_issue", "historical_diff_status": "verified"})
    return rows


class AllocationTests(unittest.TestCase):
    def test_backtracking_fills_what_the_old_greedy_could_not(self):
        self.assertEqual(old_greedy_total(HARD), 18)
        alloc = sc.allocate(HARD, REPOS)
        self.assertEqual(sum(sum(a.values()) for a in alloc.values()), 24)
        for r in REPOS:
            self.assertEqual(sum(alloc[r].values()), 8)
            for c in sc.QUOTAS:
                self.assertLessEqual(alloc[r][c], HARD[r][c])
        for c, q in sc.QUOTAS.items():
            self.assertEqual(sum(alloc[r][c] for r in REPOS), q)
        self.assertEqual(sc.shortfalls(HARD, alloc, REPOS), [])

    def test_infeasible_pool_reports_its_shortfall(self):
        avail = {r: dict(HARD[r]) for r in REPOS}
        avail["arrow"]["requirement_changed"] = 0
        avail["airflow"]["requirement_changed"] = 0          # no requirement_changed anywhere
        alloc = sc.allocate(avail, REPOS)
        self.assertEqual(sc.max_total(avail, REPOS, list(sc.QUOTAS), sc.QUOTAS, sc.PER_REPO),
                         sum(sum(a.values()) for a in alloc.values()))
        short = sc.shortfalls(avail, alloc, REPOS)
        cats = {s["what"]: s for s in short}
        self.assertEqual(cats["requirement_changed"]["got"], 0)
        self.assertIn("only 0 included pool rows", cats["requirement_changed"]["reason"])
        self.assertTrue(any(s["what"] in REPOS for s in short))   # some repo is below 8 too

    def test_quotas_total_24_and_8_per_repo(self):
        self.assertEqual(sc.QUOTAS, {"supported_approval": 7, "ownership_gap": 6, "no_approval": 7,
                                     "requirement_changed": 2, "no_key": 2})
        self.assertEqual(sum(sc.QUOTAS.values()), 24)
        self.assertEqual(sc.PER_REPO, 8)
        self.assertEqual(sc.DEFAULT_REPOS, REPOS)


class ChoiceTests(unittest.TestCase):
    def test_preference_order(self):
        rows = [{"pr_number": "1", "link_status": "uncertain", "requirement_quality": "explicit_criteria",
                 "historical_diff_status": "verified"},
                {"pr_number": "2", "link_status": "verified", "requirement_quality": "title_only",
                 "historical_diff_status": "verified"},
                {"pr_number": "3", "link_status": "verified", "requirement_quality": "descriptive_issue",
                 "historical_diff_status": "unverifiable"},
                {"pr_number": "4", "link_status": "verified", "requirement_quality": "explicit_criteria",
                 "historical_diff_status": "verified"}]
        for r in rows:
            r["provisional_category"] = "supported_approval"
        alloc = {"airflow": {"supported_approval": 3}}
        got = sc.choose({"airflow": rows}, alloc, ["airflow"])["airflow"]
        self.assertEqual([x["pr_number"] for x in got], ["4", "3", "2"])

    def test_same_seed_same_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            avail = {r: {c: 10 for c in sc.QUOTAS} for r in REPOS}
            for i, r in enumerate(REPOS):
                rows = pool_rows(r, avail[r], start=1000 * (i + 1))
                write_csv(tmp / f"{r}_pool.csv", rows, list(rows[0]))
            outs = []
            for run in ("a", "b", "c"):
                seed = sc.SEED if run != "c" else 1
                cases, rep = tmp / f"cases_{run}.csv", tmp / f"report_{run}.md"
                with contextlib.redirect_stdout(io.StringIO()):
                    sc.main(["--pool-dir", str(tmp), "--cases", str(cases), "--report", str(rep), "--seed", str(seed)])
                outs.append((cases.read_text(encoding="utf-8"), rep.read_text(encoding="utf-8")))
            self.assertEqual(outs[0], outs[1])
            self.assertNotEqual(outs[0][0], outs[2][0])
            cases = read_csv(tmp / "cases_a.csv")
            self.assertEqual(len(cases), 24)
            self.assertEqual(Counter_of(cases, "repo"), {"airflow": 8, "arrow": 8, "spark": 8})
            report = outs[0][1]
            self.assertIn("Seed 20261114", report)
            self.assertIn("proposed, pending team approval", report)
            self.assertIn("sha256", report)
            self.assertNotRegex(report, r"Run on \d{4}-\d{2}-\d{2}")

    def test_refuses_to_overwrite_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases.csv"
            cases.write_text("case_id,repo\nAF-01,airflow\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                sc.main(["--cases", str(cases), "--report", str(Path(tmp) / "r.md")])


def Counter_of(rows, field):
    out: dict[str, int] = {}
    for r in rows:
        out[r[field]] = out.get(r[field], 0) + 1
    return out


if __name__ == "__main__":
    unittest.main()
