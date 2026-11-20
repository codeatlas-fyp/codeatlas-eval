"""Tests for reviews at the merge (A4): build_pool.py, update_pool.py and freeze_case.py (standard library only).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_pool as bp
import freeze_case as fc
import update_pool as up

MERGED = "2019-10-01T12:00:00Z"
HEAD = "h" * 40


def review(login, state, at, commit=HEAD):
    return {"user": {"login": login}, "state": state, "submitted_at": at, "commit_id": commit}


class ApprovalsByMergeTests(unittest.TestCase):
    def test_approval_after_merge_is_not_counted(self):
        reviews = [review("late", "APPROVED", "2019-10-01T12:00:01Z")]
        self.assertEqual(bp.approvals_by_merge(reviews, MERGED), [])
        self.assertEqual(bp.approvers_on(bp.approvals_by_merge(reviews, MERGED), HEAD), set())

    def test_approval_at_the_merge_time_counts(self):
        reviews = [review("Owner", "APPROVED", MERGED), review("c", "COMMENTED", "2019-10-01T11:00:00Z")]
        self.assertEqual(bp.approvers_on(bp.approvals_by_merge(reviews, MERGED), HEAD), {"owner"})

    def test_pending_review_without_time_is_not_counted(self):
        self.assertEqual(bp.approvals_by_merge([review("p", "APPROVED", None)], MERGED), [])


class RecomputeCategoryTests(unittest.TestCase):
    ROW = {"repo": "airflow", "merged_at": MERGED, "api_head_sha": HEAD, "provisional_category": "supported_approval",
           "_files": [{"filename": "airflow/models/dag.py"}]}

    def test_only_approval_after_merge_is_no_longer_supported(self):
        on_head, cat = up.recompute_category(dict(self.ROW), [review("late", "APPROVED", "2019-10-02T09:00:00Z")], None)
        self.assertEqual(on_head, 0)
        self.assertNotEqual(cat, "supported_approval")

    def test_approval_before_merge_still_supported(self):
        on_head, cat = up.recompute_category(dict(self.ROW), [review("a", "APPROVED", "2019-10-01T09:00:00Z")], None)
        self.assertEqual((on_head, cat), (1, "supported_approval"))

    def test_categories_not_from_reviews_are_kept(self):
        row = dict(self.ROW, provisional_category="requirement_changed")
        self.assertEqual(up.recompute_category(row, [], None)[1], "requirement_changed")


class FreezeSplitTests(unittest.TestCase):
    def test_reviews_split_at_the_cutoff(self):
        early = review("a", "APPROVED", "2019-10-01T11:59:59Z")
        at = review("b", "COMMENTED", MERGED)
        late = review("c", "APPROVED", "2019-10-03T00:00:00Z")
        pending = review("d", "PENDING", None)
        before, after = fc.split_reviews([early, at, late, pending], MERGED)
        self.assertEqual(before, [early, at])
        self.assertEqual(after, [late, pending])

    def test_post_cutoff_file_is_mandatory(self):
        self.assertIn("sources/reviews_post_cutoff.json", fc.MANDATORY)


if __name__ == "__main__":
    unittest.main()
