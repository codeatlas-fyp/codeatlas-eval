"""Replace e-mail addresses and GitHub logins in a file with stable pseudonyms (integrity fix A6).

Usage:
    python scripts/pseudonymise.py eval/cases/AF-01/sources/reviews.json            # rewrites the file in place
    python scripts/pseudonymise.py notes.txt --out notes.pseudo.txt
    python scripts/pseudonymise.py notes.txt --map D:\\elsewhere\\pseudonyms.yaml

Each real identity gets user-01, user-02 ... in the order first seen, and keeps it in every later file and run:
the map is read from and written to ..\\codeatlas-local\\pseudonyms.yaml (outside this repository; the folder is
created if missing). The map must never be committed.

What is replaced:
- every e-mail address except placeholder and project-list addresses (allowed_email(): @example.test,
  @example.com, apache.org mailing lists);
- GitHub logins: the value of every "login" field, every @mention (not @org/team), and afterwards every
  whole-word occurrence of a login found that way (e.g. in html_url). A login that is also a common word is
  replaced there too: over-replacing is the safe side.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT.parent / "codeatlas-local" / "pseudonyms.yaml"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
LOGIN_FIELD = re.compile(r'("login"\s*:\s*")([^"]+)(")')
MENTION = re.compile(r"(?<![\w.@/+-])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?![\w/-])")
PSEUDONYM = re.compile(r"^user-\d{2,}$")
APACHE_LISTS = {"commits", "issues", "dev", "jira", "user", "users", "notifications", "reviews", "builds", "announce",
                "general", "github", "gitbox"}


def allowed_email(address: str) -> bool:
    """Addresses that identify nobody: test placeholders, GitHub's noreply, Apache project mailing lists."""
    local, _, domain = address.lower().rpartition("@")
    if domain in ("example.test", "example.com") or domain.endswith((".example.test", ".example.com")):
        return True
    if domain == "noreply.github.com" or domain.endswith(".noreply.github.com"):
        return True
    return (domain == "apache.org" or domain.endswith(".apache.org")) and local in APACHE_LISTS


def load_map(path: Path) -> dict[str, str]:
    """The map file: one line per identity, 'real: user-NN' with the real value JSON-quoted (valid YAML)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        real, _, pseudo = line.rpartition(": ")
        out[json.loads(real)] = pseudo.strip()
    return out


def save_map(path: Path, mapping: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# real identity -> pseudonym. PRIVATE: never commit, never copy into the repository."]
    lines += [f"{json.dumps(k, ensure_ascii=False)}: {v}" for k, v in sorted(mapping.items(), key=lambda kv: kv[1])]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Pseudonymiser:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping   # keys: lower-case e-mail or "github:<login lower case>"

    def _next(self) -> str:
        nums = [int(v.split("-")[1]) for v in self.mapping.values() if PSEUDONYM.match(v)]
        return f"user-{max(nums, default=0) + 1:02d}"

    def of(self, kind: str, value: str) -> str:
        key = value.lower() if kind == "email" else f"github:{value.lower()}"
        if key not in self.mapping:
            self.mapping[key] = self._next()
        return self.mapping[key]

    def text(self, text: str) -> str:
        text = EMAIL.sub(lambda m: m[0] if allowed_email(m[0]) else self.of("email", m[0]), text)
        logins = {m[2] for m in LOGIN_FIELD.finditer(text)} | {m[1] for m in MENTION.finditer(text)}
        logins = {x for x in logins if not PSEUDONYM.match(x)}
        text = LOGIN_FIELD.sub(lambda m: m[1] + (m[2] if PSEUDONYM.match(m[2]) else self.of("login", m[2])) + m[3], text)
        text = MENTION.sub(lambda m: "@" + (m[1] if PSEUDONYM.match(m[1]) else self.of("login", m[1])), text)
        for login in sorted(logins, key=len, reverse=True):   # html_url, "by <login>", ...
            text = re.sub(rf"(?<![\w-]){re.escape(login)}(?![\w-])", self.of("login", login), text, flags=re.IGNORECASE)
        return text


def pseudonymise_file(src: Path, dest: Path | None = None, map_path: Path = DEFAULT_MAP) -> int:
    """Rewrite src (or write dest). Returns how many new identities were added to the map."""
    mapping = load_map(map_path)
    before = len(mapping)
    p = Pseudonymiser(mapping)
    out = p.text(src.read_text(encoding="utf-8"))
    (dest or src).write_text(out, encoding="utf-8")
    save_map(map_path, mapping)
    return len(mapping) - before


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, help="write here instead of rewriting the file")
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP, help="pseudonym map (default ..\\codeatlas-local)")
    a = ap.parse_args(argv)
    if a.map.resolve().is_relative_to(ROOT):
        raise SystemExit("the pseudonym map must stay outside the repository")
    added = pseudonymise_file(a.file, a.out, a.map)
    print(f"{a.out or a.file}: pseudonymised ({added} new identities in the map)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
