"""Case groups in the sampler and the dev-case tool (audit 21 Nov; standard library only, synthetic data).

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
import dev_cases as dc
import sample_cases as sc
from common import read_csv, write_csv


def row(pr, cat="supported_approval", key=None, **kw):
    base = {"repo": "airflow", "pr_number": str(pr), "pr_url": f"u/{pr}", "merged_at": "2022-04-01T00:00:00Z",
            "provisional_category": cat, "included": "yes", "keys_found": key or f"K-{pr}",
            "link_status": "verified", "requirement_quality": "explicit_criteria",
            "historical_diff_status": "verified", "historical_content_status": "identical",
            "jira_history": f"{key or f'K-{pr}'}:jira_rest_cache", "py_files_changed": "1", "files_changed": "1",
            "title": f"PR {pr}", "base_at_merge": "b", "head_at_merge": "h", "merge_base_sha": "m"}
    base.update(kw)
    return base


class CaseGroupFileTests(unittest.TestCase):
    def test_load_and_reject_a_pr_in_two_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "g.csv"
            write_csv(p, [{"group_id": "G1", "repo": "airflow", "pr_number": "1", "reason": "r", "decided_on": "d"},
                          {"group_id": "G1", "repo": "airflow", "pr_number": "2", "reason": "r", "decided_on": "d"}],
                      cg.GROUP_FIELDS)
            g = cg.load_groups(p)
            self.assertEqual(cg.group_of(g, "airflow", "2"), "G1")
            self.assertEqual(cg.group_of(g, "airflow", "3"), "")
            write_csv(p, [{"group_id": "G1", "repo": "airflow", "pr_number": "1", "reason": "", "decided_on": ""},
                          {"group_id": "G2", "repo": "airflow", "pr_number": "1", "reason": "", "decided_on": ""}],
                      cg.GROUP_FIELDS)
            with self.assertRaises(SystemExit):
                cg.load_groups(p)

    def test_shared_keys_reported(self):
        rows = [row(1, key="K-9"), row(2, key="K-9;K-3"), row(3, key="K-3"), row(4)]
        self.assertEqual(dict(cg.shared_keys(rows)), {"K-3": ["airflow #2", "airflow #3"],
                                                      "K-9": ["airflow #1", "airflow #2"]})


class SamplerGroupTests(unittest.TestCase):
    def test_one_pr_per_group(self):
        rows = [row(1), row(2), row(3)]
        groups = {("airflow", "1"): "G", ("airflow", "2"): "G"}
        got = sc.choose({"airflow": rows}, {"airflow": {"supported_approval": 2}}, ["airflow"], groups=groups)
        prs = [x["pr_number"] for x in got["airflow"]]
        self.assertEqual(len(prs), 2)
        self.assertIn("3", prs)
        self.assertEqual(len({"1", "2"} & set(prs)), 1)

    def test_group_shortfall_reported(self):
        rows = [row(1), row(2)]
        groups = {("airflow", "1"): "G", ("airflow", "2"): "G"}
        alloc = {"airflow": {c: 0 for c in sc.QUOTAS}}
        alloc["airflow"]["supported_approval"] = 2
        taken = sc.choose({"airflow": rows}, alloc, ["airflow"], groups=groups)
        self.assertEqual(len(taken["airflow"]), 1)

    def test_content_status_preferred(self):
        rows = [row(1, historical_content_status="differs"), row(2)]
        got = sc.choose({"airflow": rows}, {"airflow": {"supported_approval": 1}}, ["airflow"])
        self.assertEqual(got["airflow"][0]["pr_number"], "2")


class DevCaseTests(unittest.TestCase):
    def test_problems(self):
        scored = [row(10, key="K-1")]
        self.assertEqual(dc.problems(row(1, key="K-2"), scored, {}), [])
        why = " | ".join(dc.problems(row(2, key="K-1;K-5", requirement_quality="title_only",
                                         historical_content_status="differs", files_changed="30",
                                         jira_history="K-1:created_text_only"), scored, {}))
        for part in ("2 Jira keys", "title_only", "differs", "too large", "created_text_only", "shared with a scored"):
            self.assertIn(part, why)
        self.assertIn("it is a scored case", " ".join(dc.problems(row(10, key="K-1"), scored, {})))
        groups = {("airflow", "10"): "G", ("airflow", "3"): "G"}
        self.assertIn("case group G", " ".join(dc.problems(row(3), scored, groups)))

    def test_check(self):
        scored = [row(10, key="K-S")]
        dev = [dict(row(1), case_id="AF-D01", set="dev"), dict(row(2, repo="arrow"), case_id="AR-D01", set="dev"),
               dict(row(3, repo="spark"), case_id="SP-D01", set="dev")]
        self.assertEqual(dc.check(dev, scored, {}, ["airflow", "arrow", "spark"]), [])
        bad = dev + [dict(row(4, key="K-S"), case_id="AF-D02", set="pilot")]
        msgs = " | ".join(dc.check(bad, scored, {}, ["airflow", "arrow", "spark"]))
        self.assertIn("not 'dev'", msgs)
        self.assertIn("K-S", msgs)
        self.assertIn("airflow: 2 dev cases", msgs)

    def test_add_writes_a_dev_row_and_refuses_ineligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pool = [row(1), row(2, key="K-1;K-2")]
            write_csv(tmp / "airflow_pool.csv", pool, list(pool[0]))
            cases = tmp / "cases.csv"
            write_csv(cases, [], dc.case_fields())
            dev = tmp / "dev.csv"
            args = ["--pool-dir", str(tmp), "--cases", str(cases), "--dev", str(dev)]
            with contextlib.redirect_stdout(io.StringIO()):
                dc.main(["--add", "airflow", "1", "--reason", "small", *args])
            got = read_csv(dev)
            self.assertEqual((got[0]["case_id"], got[0]["set"], got[0]["source_dir"]),
                             ("AF-D01", "dev", "eval/dev_cases/AF-D01/sources"))
            self.assertEqual(list(got[0]), dc.case_fields())
            with self.assertRaises(SystemExit) as e, contextlib.redirect_stdout(io.StringIO()):
                dc.main(["--add", "airflow", "2", "--reason", "x", *args])
            self.assertIn("2 Jira keys", str(e.exception))


if __name__ == "__main__":
    unittest.main()
