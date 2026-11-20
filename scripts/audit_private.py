"""Fail if any tracked file holds private data (integrity fix A6). Run before every push.

Usage:
    python scripts/audit_private.py               # every file `git ls-files` lists
    python scripts/audit_private.py a.txt b.json  # only these files

Flags, with file and line (never the matched value, which may be a secret):
- an e-mail address, except @example.test, @example.com, noreply.github.com and Apache mailing-list addresses
  (pseudonymise.allowed_email);
- a token-like string: GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_), Atlassian API tokens (ATATT),
  AWS access keys, Slack tokens, private-key blocks, "Bearer <long value>";
- a tracked pseudonym map (pseudonyms*.yaml) or anything under sources/, eval/pool/raw/ or eval/repos/.
Exit code 1 if anything is found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from pseudonymise import EMAIL, allowed_email

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATTERNS = {
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "Atlassian API token": re.compile(r"\bATATT[A-Za-z0-9_\-=]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9_\-.=]{30,}"),
}
FORBIDDEN_PATH = re.compile(r"(^|/)pseudonyms[^/]*\.ya?ml$|(^|/)sources/|^eval/pool/raw/|^eval/repos/")


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [root / p for p in out.split("\0") if p]


def scan_text(text: str) -> list[tuple[int, str]]:
    """(line number, what was found) for every finding in a text."""
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        for m in EMAIL.finditer(line):
            if not allowed_email(m[0]):
                found.append((n, "e-mail address"))
        for kind, pat in TOKEN_PATTERNS.items():
            if pat.search(line):
                found.append((n, kind))
    return found


def audit(paths: list[Path], root: Path = ROOT) -> list[str]:
    problems = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()
        if FORBIDDEN_PATH.search(rel):
            problems.append(f"{rel}: file must not be tracked (private data)")
        if not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:   # binary
            continue
        for n, kind in scan_text(data.decode("utf-8", errors="replace")):
            problems.append(f"{rel}:{n}: {kind}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", type=Path)
    a = ap.parse_args(argv)
    paths = a.paths or tracked_files(ROOT)
    problems = audit(paths)
    for p in problems:
        print(p)
    print(f"audit_private: {len(paths)} files checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
