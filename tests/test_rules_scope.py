"""Tests for eval/rules_scope.yaml (B2; standard library only, so the YAML is read with a small line parser).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SCOPE = Path(__file__).resolve().parent.parent / "eval" / "rules_scope.yaml"


def read_scope() -> dict[str, dict[str, str]]:
    """{rule: {field: value}} for the two-level 'rules:' mapping; folded (>-) values are joined."""
    rules: dict[str, dict[str, str]] = {}
    rule = field = None
    for line in SCOPE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if m := re.match(r"^  (C\d):\s*$", line):
            rule, field = m[1], None
            rules[rule] = {}
        elif rule and (m := re.match(r"^    (\w+):\s*(.*)$", line)):
            field = m[1]
            rules[rule][field] = "" if m[2] == ">-" else m[2]
        elif rule and field and line.startswith("      "):
            rules[rule][field] = (rules[rule][field] + " " + line.strip()).strip()
    return rules


class RulesScopeTests(unittest.TestCase):
    def test_lists_all_nine_rules(self):
        self.assertEqual(sorted(read_scope()), [f"C{i}" for i in range(1, 10)])

    def test_every_rule_has_a_flag_and_every_false_entry_a_reason(self):
        for rule, entry in read_scope().items():
            self.assertIn(entry.get("estimable_on_real_data"), ("true", "false"), rule)
            if entry["estimable_on_real_data"] == "false":
                self.assertGreater(len(entry.get("reason", "")), 20, f"{rule} has no reason")
                self.assertTrue(entry.get("tested_instead"), f"{rule} does not say where it is tested")

    def test_c5_is_not_estimable(self):
        self.assertEqual(read_scope()["C5"]["estimable_on_real_data"], "false")


if __name__ == "__main__":
    unittest.main()
