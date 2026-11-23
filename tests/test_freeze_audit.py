"""Freeze changes from the 21 Nov audit: policy snapshot, DRAFT gate, stale labels, dev cases, packet/ folder.

    python -m unittest discover -s tests -v

Standard library only, no network: collect() is replaced by a fake that writes the evidence files.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import freeze_case as fc
from test_freeze_atomic import ROW, quiet

EVIDENCE = {"text": "issue text v1\n"}


def snapshot_collect(row, case_dir):
    """Writes the evidence and, like the real collect(), the exact policy bytes."""
    src = case_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)
    for rel in fc.MANDATORY:
        (case_dir / rel).write_text(f"{rel} of {row['case_id']}\n", encoding="utf-8")
    path, digest, _ = fc.policy_for(row["repo"])
    (case_dir / fc.POLICY_SNAPSHOT).write_bytes(path.read_bytes())
    (src / "jira_AIRFLOW-1_at_cutoff.txt").write_text(EVIDENCE["text"], encoding="utf-8")
    (src / "fetched_at.txt").write_text(f"{fc._stamp()}\n", encoding="utf-8")   # differs every run: ignored
    return {"mandatory": ["sources/jira_AIRFLOW-1_at_cutoff.txt"], "refs": {"policy_sha256": digest}}


class AuditFreezeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.final = self.out / "AF-01"
        EVIDENCE["text"] = "issue text v1\n"

    def tearDown(self):
        self._tmp.cleanup()

    def freeze(self, row=None, **kwargs):
        kwargs.setdefault("allow_draft", True)
        with mock.patch.object(fc, "collect", side_effect=snapshot_collect):
            return quiet(fc.freeze, dict(row or ROW), self.out, **kwargs)

    def test_policy_bytes_are_frozen_and_checked(self):
        self.freeze()
        snap = self.final / fc.POLICY_SNAPSHOT
        self.assertEqual(snap.read_bytes(), (fc.POLICIES / "airflow.yaml").read_bytes())
        self.assertIn(fc.POLICY_SNAPSHOT, fc.MANDATORY)
        self.assertEqual(fc.verify_case(self.final), [])
        snap.write_text("version: 1\n# edited later\n", encoding="utf-8")
        reasons = fc.verify_case(self.final)
        self.assertIn(f"checksum mismatch: {fc.POLICY_SNAPSHOT}", reasons)
        self.assertIn(f"{fc.POLICY_SNAPSHOT} does not match policy_sha256 in the manifest refs", reasons)

    def test_draft_policy_refuses_a_scored_case(self):
        draft = (fc.POLICIES / "airflow.yaml").read_text(encoding="utf-8").replace(
            "status: SIGNED OFF", "status: DRAFT until signed off, was SIGNED OFF")
        with tempfile.TemporaryDirectory() as pol:
            (Path(pol) / "airflow.yaml").write_text(draft, encoding="utf-8")
            with mock.patch.object(fc, "POLICIES", Path(pol)), \
                    mock.patch.object(fc, "collect", side_effect=AssertionError("must not collect")):
                with self.assertRaises(SystemExit) as ctx:
                    quiet(fc.freeze, dict(ROW), self.out)            # set pilot, no --allow-draft
            self.assertIn("still DRAFT", str(ctx.exception))
            self.assertFalse(self.out.joinpath("AF-01").exists())
            self.assertFalse(self.out.joinpath("AF-01.staging").exists())

    def test_draft_policy_freezes_a_dev_case(self):
        dev = dict(ROW, case_id="AF-D01", set="dev")
        result, _ = self.freeze(dev, allow_draft=False)
        self.assertEqual(result, "frozen")
        self.assertEqual(fc.verify_case(self.out / "AF-D01"), [])

    def test_signed_policy_freezes_a_scored_case(self):
        signed = (fc.POLICIES / "airflow.yaml").read_text(encoding="utf-8").replace(
            "status: DRAFT until signed off by Areej, Yusra, Saleha", "status: SIGNED OFF 2026-11-22")
        with tempfile.TemporaryDirectory() as pol:
            (Path(pol) / "airflow.yaml").write_text(signed, encoding="utf-8")
            with mock.patch.object(fc, "POLICIES", Path(pol)):
                result, _ = self.freeze(allow_draft=False)
                self.assertEqual(result, "frozen")
                self.assertEqual((self.final / fc.POLICY_SNAPSHOT).read_text(encoding="utf-8"), signed)

    def test_dev_cases_freeze_into_their_own_folder_by_default(self):
        self.assertEqual(fc.out_root_for({"set": "dev"}, None), fc.EVAL / "dev_cases")
        self.assertEqual(fc.out_root_for({"set": "pilot"}, None), fc.EVAL / "cases")
        self.assertEqual(fc.out_root_for({"set": "challenge"}, None), fc.EVAL / "challenge")

    def test_refresh_with_changed_evidence_marks_filled_labels_stale(self):
        self.freeze()
        (self.final / "label_A.yaml").write_text("rules: {C1: {result: SATISFIED}}\n", encoding="utf-8")
        EVIDENCE["text"] = "issue text v2: edited\n"
        result, out = self.freeze(refresh=True)
        self.assertEqual(result, "frozen")
        note = fc.stale_note(self.final)
        self.assertIsNotNone(note)
        self.assertIn("label_A.yaml", note)
        self.assertIn("Changed: sources/jira_AIRFLOW-1_at_cutoff.txt", note)
        self.assertNotIn("fetched_at", note)
        self.assertEqual((self.final / "label_A.yaml").read_text(encoding="utf-8"),
                         "rules: {C1: {result: SATISFIED}}\n")   # carried, never overwritten
        self.assertEqual(fc.verify_case(self.final), [])            # evidence itself is a valid freeze
        code, printed = quiet(fc.verify, [self.out], None)
        self.assertIn("labels STALE", printed)
        self.assertIn("1 with stale labels", printed)

    def test_refresh_with_same_evidence_keeps_labels_valid(self):
        self.freeze()
        (self.final / "label_A.yaml").write_text("rules: {C1: {result: SATISFIED}}\n", encoding="utf-8")
        self.freeze(refresh=True)
        self.assertIsNone(fc.stale_note(self.final))

    def test_refresh_of_blank_templates_is_never_stale(self):
        self.freeze()
        EVIDENCE["text"] = "issue text v2: edited\n"
        self.freeze(refresh=True)
        self.assertIsNone(fc.stale_note(self.final))

    def test_stale_mark_survives_a_second_refresh(self):
        self.freeze()
        (self.final / "label_B.yaml").write_text("rules: {}\nlabeller: x\n", encoding="utf-8")
        EVIDENCE["text"] = "v2\n"
        self.freeze(refresh=True)
        self.freeze(refresh=True)                    # same evidence as v2, but labels were already stale
        note = fc.stale_note(self.final)
        self.assertIsNotNone(note)
        self.assertIn("Already stale before this refreeze", note)

    def test_packet_and_stale_files_are_outside_the_manifest(self):
        self.freeze()
        (self.final / "packet").mkdir()
        (self.final / "packet" / "criteria.csv").write_text("criterion_id,text\n", encoding="utf-8")
        (self.final / fc.STALE).write_text("x\n", encoding="utf-8")
        self.assertEqual(fc.verify_case(self.final), [])


if __name__ == "__main__":
    unittest.main()
