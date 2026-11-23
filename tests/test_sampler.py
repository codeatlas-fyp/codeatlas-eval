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

import case_groups as cg
import sample_cases as sc
from common import read_csv, write_csv

REPOS = ["airflow", "arrow", "spark"]
# the 24-case quotas of 20 Nov: the allocation must still reach them when the sprint's 9 are extended to 24
QUOTAS_24 = {"supported_approval": 7, "ownership_gap": 6, "no_approval": 7, "requirement_changed": 2, "no_key": 2}
PER_REPO_24 = 8
# the old greedy (category by category, round robin over repos) reaches 18 here; 24 is feasible
HARD = {"airflow": {"supported_approval": 8, "ownership_gap": 8, "no_approval": 8, "requirement_changed": 2, "no_key": 0},
        "arrow": {"supported_approval": 0, "ownership_gap": 5, "no_approval": 0, "requirement_changed": 8, "no_key": 2},
        "spark": {"supported_approval": 8, "ownership_gap": 0, "no_approval": 0, "requirement_changed": 0, "no_key": 1}}


def old_greedy_total(avail, quotas=QUOTAS_24, per_repo=PER_REPO_24):
    """The allocation the sampler used before Part C, counts only."""
    taken = {r: 0 for r in REPOS}
    total = 0
    for c, target in quotas.items():
        left = dict((r, avail[r][c]) for r in REPOS)
        got = 0
        while got < target and any(left.values()):
            for r in REPOS:
                if got >= target:
                    break
                if left[r] and taken[r] < per_repo:
                    taken[r] += 1
                    left[r] -= 1
                    got += 1
            if all(taken[r] >= per_repo or not left[r] for r in REPOS):
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
        alloc = sc.allocate(HARD, REPOS, QUOTAS_24, PER_REPO_24)
        self.assertEqual(sum(sum(a.values()) for a in alloc.values()), 24)
        for r in REPOS:
            self.assertEqual(sum(alloc[r].values()), 8)
            for c in QUOTAS_24:
                self.assertLessEqual(alloc[r][c], HARD[r][c])
        for c, q in QUOTAS_24.items():
            self.assertEqual(sum(alloc[r][c] for r in REPOS), q)
        self.assertEqual(sc.shortfalls(HARD, alloc, REPOS, QUOTAS_24, PER_REPO_24), [])

    def test_nine_cases_three_per_repo_on_a_hard_pool(self):
        alloc = sc.allocate(HARD, REPOS)
        for r in REPOS:
            self.assertEqual(sum(alloc[r].values()), 3)
        for c, q in sc.QUOTAS.items():
            self.assertEqual(sum(alloc[r][c] for r in REPOS), q)
        self.assertEqual(sc.shortfalls(HARD, alloc, REPOS), [])

    def test_infeasible_pool_reports_its_shortfall(self):
        avail = {r: dict(HARD[r]) for r in REPOS}
        avail["arrow"]["requirement_changed"] = 0
        avail["airflow"]["requirement_changed"] = 0          # no requirement_changed anywhere
        alloc = sc.allocate(avail, REPOS, QUOTAS_24, PER_REPO_24)
        self.assertEqual(sc.max_total(avail, REPOS, list(QUOTAS_24), QUOTAS_24, PER_REPO_24),
                         sum(sum(a.values()) for a in alloc.values()))
        short = sc.shortfalls(avail, alloc, REPOS, QUOTAS_24, PER_REPO_24)
        cats = {s["what"]: s for s in short}
        self.assertEqual(cats["requirement_changed"]["got"], 0)
        self.assertIn("only 0 included pool rows", cats["requirement_changed"]["reason"])
        self.assertTrue(any(s["what"] in REPOS for s in short))   # some repo is below 8 too

    def test_quotas_total_9_and_3_per_repo(self):
        self.assertEqual(sc.QUOTAS, {"supported_approval": 3, "ownership_gap": 2, "no_approval": 2,
                                     "requirement_changed": 1, "no_key": 1})
        self.assertEqual(sum(sc.QUOTAS.values()), 9)
        self.assertEqual(sc.PER_REPO, 3)
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
            self.assertEqual(len(cases), 9)
            self.assertEqual(Counter_of(cases, "repo"), {"airflow": 3, "arrow": 3, "spark": 3})
            self.assertEqual({c["set"] for c in cases}, {"pilot"})   # no rare candidate in these pools
            report = outs[0][1]
            self.assertIn("Seed 20261114", report)
            self.assertIn("Dataset Plan (Final), 21 Nov 2026", report)
            self.assertIn("Chosen: none", report)
            self.assertIn("sha256", report)
            self.assertNotRegex(report, r"Run on \d{4}-\d{2}-\d{2}")

    def test_refuses_to_overwrite_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases.csv"
            cases.write_text("case_id,repo\nAF-01,airflow\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                sc.main(["--cases", str(cases), "--report", str(Path(tmp) / "r.md")])


class RevertTests(unittest.TestCase):
    def test_is_revert_reads_the_start_of_the_title(self):
        reverts = ['Revert "[AIRFLOW-5490] Fix incorrect None comparison"', "ARROW-16434: [R][CI] Revert devdocs",
                   "[SPARK-34079][SQL][FOLLOW-UP] Revert some changes", "revert: undo", "[AIRFLOW-2] Revert x"]
        kept = ["[AIRFLOW-1] Add a revert button", "Reverting is not a revert PR", "ARROW-3: Fix revert path", ""]
        for t in reverts:
            self.assertTrue(cg.is_revert({"title": t}), t)
        for t in kept:
            self.assertFalse(cg.is_revert({"title": t}), t)
        self.assertFalse(cg.is_revert({}))

    def test_sampler_never_draws_a_revert_and_reports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            avail = {r: {c: 3 for c in sc.QUOTAS} for r in REPOS}
            for i, r in enumerate(REPOS):
                rows = pool_rows(r, avail[r], start=1000 * (i + 1))
                if r == "airflow":   # every airflow no_key row is a revert, so that cell is empty
                    for x in rows:
                        x["title"] = 'Revert "x"' if x["provisional_category"] == "no_key" else "[K-1] Add x"
                write_csv(tmp / f"{r}_pool.csv", rows, list(rows[0]))
            cases, rep = tmp / "cases.csv", tmp / "report.md"
            with contextlib.redirect_stdout(io.StringIO()):
                sc.main(["--pool-dir", str(tmp), "--cases", str(cases), "--report", str(rep)])
            got = read_csv(cases)
            self.assertEqual(len(got), 9)
            self.assertFalse([c for c in got if c["repo"] == "airflow" and c["category_provisional"] == "no_key"])
            self.assertIn("| airflow | 3 | #1013, #1014, #1015 |", rep.read_text(encoding="utf-8"))


class RareCaseTests(unittest.TestCase):
    ORDER = [("arrow", "5"), ("airflow", "6"), ("airflow", "7")]

    def pools(self):
        return {"airflow": [{"pr_number": n} for n in ("1", "6", "7")], "arrow": [{"pr_number": "5"}]}

    def test_first_in_the_seeded_order(self):
        (repo, row), passed = sc.rare_case(self.pools(), {"airflow": [], "arrow": []}, order=self.ORDER)
        self.assertEqual((repo, row["pr_number"], passed), ("arrow", "5", []))

    def test_skips_drawn_grouped_missing_and_unfrozen(self):
        pools = self.pools()
        pools["arrow"] = []                                   # arrow #5 left the pool
        taken = {"airflow": [{"pr_number": "1"}], "arrow": []}
        groups = {("airflow", "1"): "G", ("airflow", "6"): "G"}
        pick, passed = sc.rare_case(pools, taken, groups, order=self.ORDER)
        self.assertEqual(pick[1]["pr_number"], "7")
        self.assertEqual(passed, ["arrow #5: not in the included pool rows", "airflow #6: case group G has a drawn PR"])
        pick, passed = sc.rare_case(pools, taken, groups, skip={("airflow", "7")}, order=self.ORDER)
        self.assertIsNone(pick)
        self.assertIn("airflow #7: skipped by --rare-skip", passed[-1])
        taken["airflow"].append({"pr_number": "7"})
        self.assertIn("in the 9-case draw", sc.rare_case(pools, taken, {}, order=self.ORDER[2:])[1][0])

    def test_rare_order_is_the_plans(self):
        self.assertEqual(sc.RARE_ORDER[0], ("arrow", "12672"))
        self.assertEqual(len(sc.RARE_ORDER), 5)

    def test_main_adds_the_rare_case_as_its_own_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            avail = {r: {c: 3 for c in sc.QUOTAS} for r in REPOS}
            for i, r in enumerate(REPOS):
                rows = pool_rows(r, avail[r], start=1000 * (i + 1))
                if r == "arrow":
                    rows.append(dict(rows[0], pr_number="12672", pr_url="u/12672", provisional_category="ownership_gap",
                                     link_status="uncertain"))   # last in its cell, so never drawn
                write_csv(tmp / f"{r}_pool.csv", rows, list(rows[0]))
            cases, rep = tmp / "cases.csv", tmp / "report.md"
            with contextlib.redirect_stdout(io.StringIO()):
                sc.main(["--pool-dir", str(tmp), "--cases", str(cases), "--report", str(rep)])
            got = read_csv(cases)
            self.assertEqual(len(got), 10)
            rare = [c for c in got if c["set"] == "rare"]
            self.assertEqual([(c["case_id"], c["pr_number"], c["source_dir"]) for c in rare],
                             [("AR-R01", "12672", "eval/cases/AR-R01/sources")])
            self.assertIn("Chosen: AR-R01 = arrow #12672", rep.read_text(encoding="utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                sc.main(["--pool-dir", str(tmp), "--cases", str(cases), "--report", str(rep), "--force",
                         "--rare-skip", "arrow#12672"])
            self.assertFalse([c for c in read_csv(cases) if c["set"] == "rare"])


def Counter_of(rows, field):
    out: dict[str, int] = {}
    for r in rows:
        out[r[field]] = out.get(r[field], 0) + 1
    return out


if __name__ == "__main__":
    unittest.main()
