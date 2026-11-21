"""Tests for scripts/prepare_packets.py with a stub prepare_case.py (standard library only, no CodeAtlas needed).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import prepare_packets as pp
from common import read_csv

HEAD = "a" * 40
# Stub with the real tool's interface: one criterion per non-empty line; the entity list depends only on repo+root.
STUB = textwrap.dedent('''
    import argparse, csv, sys
    from pathlib import Path
    ap = argparse.ArgumentParser()
    for f in ("--repo", "--key", "--version", "--issue-text", "--root", "--out"):
        ap.add_argument(f, required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    text = Path(a.issue_text).read_text(encoding="utf-8")
    if "FAIL" in text:
        sys.exit(3)
    lines = [l for l in text.splitlines() if l.strip()]
    with (out / "criteria.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h, lineterminator="\\n"); w.writerow(["criterion_id", "key", "version_no", "criterion_text"])
        for i, l in enumerate(lines, 1):
            w.writerow([f"{a.key}:v{a.version}:ac{i}", a.key, a.version, l])
    ent = "entity_id,label_ref\\n" + f"e1,{a.root or 'x'}/m.py::f\\n"
    if "OTHER" in text:
        ent += "e2,other\\n"
    (out / "entities.csv").write_text(ent, encoding="utf-8")
    print(f"repo @ {a.repo}")
''')


def cutoff(key, status, text):
    return (f"key: {key}\nsource: jira_rest_cache\ncutoff: 2022-04-01T00:00:00Z\nreconstruction_status: {status}\n"
            f"reconstruction_note: x\n---\n{text}")


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.codeatlas = t / "codeatlas"
        (self.codeatlas / "scripts").mkdir(parents=True)
        (self.codeatlas / "scripts" / "prepare_case.py").write_text(STUB, encoding="utf-8")
        self.cmd = [sys.executable, "scripts/prepare_case.py"]
        self.case = t / "AF-D01"
        (self.case / "sources").mkdir(parents=True)
        (self.case / "case.yaml").write_text(
            f"case_id: AF-D01\nset: dev                         # pilot | dev\nrepo: apache/airflow\n"
            f"head_at_merge: {HEAD}         # 2nd parent\nanalysis_root: python/\n", encoding="utf-8")
        self.links([("K-1", "verified"), ("K-2", "verified"), ("K-3", "uncertain")])
        self.write("K-1", "reconstructed", "Fix the thing\n\nIt must not crash.\n")
        self.write("K-2", "created_text_only", "Second issue\n")
        self.write("K-3", "reconstructed", "Uncertain link\n")

    def tearDown(self):
        self.tmp.cleanup()

    def links(self, pairs):
        (self.case / "sources" / "jira_links.json").write_text(
            json.dumps({"links": [{"key": k, "status": s} for k, s in pairs]}), encoding="utf-8")

    def write(self, key, status, text):
        (self.case / "sources" / f"jira_{key}_at_cutoff.txt").write_text(cutoff(key, status, text), encoding="utf-8")

    def build(self, **kw):
        return pp.build(self.case, self.codeatlas, self.cmd, clone=Path("/clones/airflow"), **kw)

    def test_header_is_stripped(self):
        header, text = pp.split_cutoff_file(cutoff("K-1", "reconstructed", "Title\n\nBody\n"))
        self.assertEqual(header["reconstruction_status"], "reconstructed")
        self.assertEqual(text, "Title\n\nBody\n")
        with self.assertRaises(ValueError):
            pp.split_cutoff_file("no header here\n")

    def test_multi_key_merge(self):
        meta = self.build()
        crit = read_csv(self.case / "packet" / "criteria.csv")
        self.assertEqual([c["criterion_id"] for c in crit], ["K-1:v1:ac1", "K-1:v1:ac2", "K-2:v1:ac1"])
        self.assertFalse(any("reconstruction_status" in c["criterion_text"] or c["criterion_text"] == "---"
                             for c in crit))
        self.assertEqual([k["key"] for k in meta["keys_used"]], ["K-1", "K-2"])
        self.assertEqual(meta["keys_skipped"][0]["key"], "K-3")
        self.assertIn("uncertain", meta["keys_skipped"][0]["reason"])
        self.assertEqual(meta["head_at_merge"], HEAD)
        self.assertEqual(meta["analysis_root"], "python")
        self.assertEqual(meta["entities"], 1)
        self.assertEqual(len(meta["prepare_case_sha256"]), 64)
        self.assertEqual((self.case / "packet" / "issue_text_K-1.txt").read_text(encoding="utf-8"),
                         "Fix the thing\n\nIt must not crash.\n")
        self.assertIn("python/m.py::f", (self.case / "packet" / "entities.csv").read_text(encoding="utf-8"))
        self.assertIn(f"/clones/airflow@{HEAD}", meta["prepare_case_output"]["K-1"])
        self.assertFalse((self.case / ".packet.tmp").exists())

    def test_refuses_to_overwrite_without_force(self):
        self.build()
        with self.assertRaises(SystemExit):
            self.build()
        self.write("K-2", "created_text_only", "Second issue\nnew line\n")
        meta = self.build(force=True)
        self.assertEqual(meta["keys_used"][1]["criteria"], 2)

    def test_unverifiable_and_empty_text_are_skipped(self):
        self.write("K-2", "unverifiable", "")
        self.links([("K-1", "verified"), ("K-2", "verified"), ("K-3", "verified")])
        self.write("K-3", "reconstructed", "   \n")
        meta = self.build()
        reasons = {s["key"]: s["reason"] for s in meta["keys_skipped"]}
        self.assertIn("unverifiable", reasons["K-2"])
        self.assertIn("empty", reasons["K-3"])

    def test_explicit_keys(self):
        meta = self.build(wanted=["K-2"])
        self.assertEqual([k["key"] for k in meta["keys_used"]], ["K-2"])
        with self.assertRaises(SystemExit):
            self.build(wanted=["K-9"], force=True)

    def test_entities_must_match_across_keys(self):
        self.write("K-2", "created_text_only", "OTHER code\n")
        with self.assertRaises(SystemExit) as e:
            self.build()
        self.assertIn("differs", str(e.exception))
        self.assertFalse((self.case / "packet").exists())

    def test_tool_failure_writes_nothing(self):
        self.write("K-2", "created_text_only", "FAIL\n")
        with self.assertRaises(SystemExit):
            self.build()
        self.assertFalse((self.case / "packet").exists())

    def test_no_usable_key(self):
        self.links([("K-1", "uncertain"), ("K-2", "uncertain"), ("K-3", "uncertain")])
        with self.assertRaises(SystemExit) as e:
            self.build()
        self.assertIn("no key to prepare", str(e.exception))


if __name__ == "__main__":
    unittest.main()
