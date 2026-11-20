"""Tests for the jira_history pool column (update_pool.key_history; standard library only, no network).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common
import update_pool as up

ROW = {"pr_number": "7", "merged_at": "2022-05-01T00:00:00Z", "included": "yes", "keys_found": "ARROW-1;ARROW-2;ARROW-3"}
REST = {"key": "ARROW-1", "fields": {"summary": "s", "description": "d"}, "changelog": {"histories": []}}
ARCHIVE_OLD = {"key": "ARROW-2", "source": "apache_mail_archive", "archive": {"list": "issues@arrow.apache.org"},
               "fields": {"summary": "s", "description": "d"}, "changelog": {"histories": []}}


class JiraHistoryTests(unittest.TestCase):
    def test_statuses_per_key_and_email_kinds_backfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp)
            pr = ev / "pool" / "raw" / "arrow" / "7"
            pr.mkdir(parents=True)
            (pr / "jira_ARROW-1.json").write_text(json.dumps(REST), encoding="utf-8")
            (pr / "jira_ARROW-2.json").write_text(json.dumps(ARCHIVE_OLD), encoding="utf-8")
            calls = []

            def kinds(key, get, lists):
                calls.append((key, lists[0]))
                return ("issues@arrow.apache.org", {"Created": 1})

            rows = [dict(ROW)]
            with mock.patch.object(up, "EVAL", ev), mock.patch.object(common, "EVAL", ev), \
                    mock.patch.object(up, "archive_email_kinds", side_effect=kinds):
                up.update_jira_history({"name": "arrow"}, rows, lambda: None)
            saved = json.loads((pr / "jira_ARROW-2.json").read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["jira_history"], "ARROW-1:jira_rest_cache;ARROW-2:created_text_only;ARROW-3:unavailable")
        self.assertEqual(calls, [("ARROW-2", "issues")])
        self.assertEqual(saved["archive"]["email_kinds"], {"Created": 1})


if __name__ == "__main__":
    unittest.main()
