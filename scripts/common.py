"""Shared helpers for the CodeAtlas dataset scripts (standard library only, read-only towards GitHub and Jira)."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
REPOS_DIR = EVAL / "repos"
USER_AGENT = "codeatlas-eval-dataset"

# ---------------------------------------------------------------- config


def load_repos() -> dict[str, dict[str, Any]]:
    data = json.loads((EVAL / "repos.json").read_text(encoding="utf-8"))
    return {r["name"]: r for r in data["repos"]}


def repo_cfg(name: str) -> dict[str, Any]:
    repos = load_repos()
    if name not in repos:
        sys.exit(f"unknown repo '{name}'; known: {', '.join(repos)}")
    return repos[name]


# ---------------------------------------------------------------- git


def git(repo_dir: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def ensure_clone(cfg: dict[str, Any], blobless: bool = False) -> Path:
    """Full clone into eval/repos/<name> (not committed). Fetches if it already exists."""
    dest = REPOS_DIR / cfg["name"]
    if (dest / ".git").exists():
        git(dest, "fetch", "--quiet", "origin")
        return dest
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--quiet"]
    if blobless:
        cmd += ["--filter=blob:none"]
    cmd += [cfg["clone_url"], str(dest)]
    print(f"cloning {cfg['clone_url']} -> {dest} (this can take several minutes)")
    subprocess.run(cmd, check=True)
    return dest


def default_branch(repo_dir: Path) -> str:
    return git(repo_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()


def first_parent_commits(repo_dir: Path, since: str, until: str) -> list[dict[str, str]]:
    """Commits on the main branch in the window, oldest first: sha, time, subject, body, parents."""
    fmt = "%H%x1f%cI%x1f%P%x1f%s%x1f%b%x1e"
    out = git(repo_dir, "log", "--first-parent", "--reverse", f"--since={since}", f"--until={until}",
              f"--format={fmt}", default_branch(repo_dir))
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, at, parents, subject, body = (rec.split("\x1f") + [""] * 5)[:5]
        commits.append({"sha": sha, "time": at, "parents": parents.split(), "subject": subject, "body": body})
    return commits


def merged_branch_messages(repo_dir: Path, commit: dict[str, str]) -> str:
    """For a true merge commit, the messages of the commits it brought in (where Jira keys often are)."""
    if len(commit["parents"]) < 2:
        return ""
    return git(repo_dir, "log", "--format=%s%n%b", f"{commit['parents'][0]}..{commit['parents'][1]}", check=False)


def file_at(repo_dir: Path, sha: str, path: str) -> str | None:
    res = subprocess.run(["git", "-C", str(repo_dir), "show", f"{sha}:{path}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.stdout if res.returncode == 0 else None


CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def codeowners_at(repo_dir: Path, sha: str) -> tuple[str | None, str | None]:
    """(path, text) of the CODEOWNERS file GitHub would use at this commit, or (None, None)."""
    for p in CODEOWNERS_PATHS:
        text = file_at(repo_dir, sha, p)
        if text is not None:
            return p, text
    return None, None


# ---------------------------------------------------------------- keys and PR numbers

PR_PATTERNS = (re.compile(r"\(#(\d+)\)\s*$"), re.compile(r"^Merge pull request #(\d+)"))


def pr_number(subject: str) -> int | None:
    for pat in PR_PATTERNS:
        m = pat.search(subject.strip())
        if m:
            return int(m.group(1))
    return None


def find_keys(text: str, key_regex: str) -> list[str]:
    return sorted({k.upper() for k in re.findall(key_regex, text or "", flags=re.IGNORECASE)})


# ---------------------------------------------------------------- CODEOWNERS (last matching line wins)


def parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    rules = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        rules.append((parts[0], parts[1:]))
    return rules


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    p = pattern.lstrip("/")
    if p.endswith("/"):
        p += "**"
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif p.startswith("**", i):
            out += ".*"; i += 2
        elif p[i] == "*":
            out += "[^/]*"; i += 1
        elif p[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(p[i]); i += 1
    prefix = "^" if anchored else "^(?:.*/)?"
    return re.compile(prefix + out + "(?:/.*)?$")


def owners_for(path: str, rules: list[tuple[str, list[str]]]) -> list[str] | None:
    """Owners of the last matching rule; None if no rule matches."""
    found = None
    for pattern, owners in rules:
        if _pattern_regex(pattern).match(path):
            found = owners
    return found


def is_team(owner: str) -> bool:
    return owner.startswith("@") and "/" in owner


# ---------------------------------------------------------------- HTTP (GET only)


def _get(url: str, headers: dict[str, str]) -> tuple[Any, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers}, method="GET")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
                wait = max(5, int(e.headers.get("X-RateLimit-Reset", "0")) - int(time.time()) + 5)
                print(f"  rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"giving up on {url}")


def github_token() -> str:
    tok = os.environ.get("CODEATLAS_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not tok:
        sys.exit("set CODEATLAS_GITHUB_TOKEN (read-only token) in your environment first")
    return tok


def gh(path: str, paginate: bool = False) -> Any:
    headers = {"Authorization": f"Bearer {github_token()}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    url = f"https://api.github.com/{path.lstrip('/')}"
    if not paginate:
        return _get(url, headers)[0]
    items, page = [], 1
    while True:
        sep = "&" if "?" in url else "?"
        batch = _get(f"{url}{sep}per_page=100&page={page}", headers)[0]
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def jira_issue(base_url: str, key: str) -> Any:
    """Apache Jira is Jira Data Center: REST API v2, anonymous read."""
    url = f"{base_url.rstrip('/')}/rest/api/2/issue/{urllib.parse.quote(key)}?expand=changelog"
    return _get(url, {"Accept": "application/json"})[0]


# ---------------------------------------------------------------- CSV


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
