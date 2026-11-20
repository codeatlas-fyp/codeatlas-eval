"""Tests for the sampling categories (B1): build_pool.approval_category (standard library only).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_pool as bp

POOLS = Path(__file__).resolve().parent.parent / "eval" / "pool"


class CategoryTests(unittest.TestCase):
    def test_keyed_pr_without_approval_is_no_approval(self):
        self.assertEqual(bp.approval_category([], set(), [], set(), False), "no_approval")

    def test_approval_by_a_non_owner_is_no_approval(self):
        approvals = [{"state": "APPROVED"}]
        self.assertEqual(bp.approval_category(approvals, {"bob"}, [["@alice"]], {"alice"}, False), "no_approval")

    def test_pools_use_only_the_controlled_categories(self):
        import csv
        allowed = {"supported_approval", "ownership_gap", "no_approval", "requirement_changed", "no_key"}
        for repo in ("airflow", "arrow", "spark"):
            with (POOLS / f"{repo}_pool.csv").open(encoding="utf-8") as f:
                cats = {r["provisional_category"] for r in csv.DictReader(f)}
            self.assertLessEqual(cats, allowed, repo)


if __name__ == "__main__":
    unittest.main()
