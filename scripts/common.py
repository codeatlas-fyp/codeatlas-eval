"""Shared helpers for the CodeAtlas dataset scripts (standard library only, read-only towards GitHub and Jira)."""

from __future__ import annotations

import csv
import http.client
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
# Apache merge scripts (Airflow before mid-2018, Arrow before 2022, Libcloud) keep the subject as the
# Jira title and write the PR number in the body: "Closes #9618 from user/branch" or "Closes #894".
BODY_PR_PATTERN = re.compile(r"^\s*Closes:?\s+#(\d+)\b", re.IGNORECASE | re.MULTILINE)


def pr_number(subject: str, body: str = "") -> int | None:
    """PR number from the merge subject, else from a "Closes #N" line in the commit body."""
    for pat in PR_PATTERNS:
        m = pat.search(subject.strip())
        if m:
            return int(m.group(1))
    m = BODY_PR_PATTERN.search(body or "")
    return int(m.group(1)) if m else None


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
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as e:
            # dropped connections ("Remote end closed connection without response") are worth a retry
            if attempt < 3:
                print(f"  network error ({type(e).__name__}); retrying in {5 * (attempt + 1)}s")
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


_JIRA_LOGIN_REQUIRED: set[str] = set()


def archive_get(url: str) -> Any:
    """GET from lists.apache.org: parsed JSON, or the raw text when the answer is not JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        except urllib.error.HTTPError as e:
            if (e.code >= 500 or e.code == 429) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"giving up on {url}")


def jira_issue(base_url: str, key: str) -> Any:
    """One Jira issue with its changelog.

    Apache Jira is Jira Data Center (REST API v2). Since 2025 it answers 401 "Login Required" to anonymous
    reads, so after the first 401 the issue is rebuilt from the public mailing-list archive instead
    (scripts/jira_archive.py). Every result carries "source": "jira_rest" or "apache_mail_archive", because the
    text at a cutoff is rebuilt differently for each (jira_archive.reconstruct_at).
    """
    from jira_archive import REST_SOURCE, archive_issue  # local import: jira_archive does not import this module

    if base_url not in _JIRA_LOGIN_REQUIRED:
        url = f"{base_url.rstrip('/')}/rest/api/2/issue/{urllib.parse.quote(key)}?expand=changelog"
        try:
            issue = _get(url, {"Accept": "application/json"})[0]
            issue["source"] = REST_SOURCE
            return issue
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403):
                raise
            _JIRA_LOGIN_REQUIRED.add(base_url)
            print(f"  jira: {base_url} needs a login (HTTP {e.code}); reading issues from lists.apache.org instead")
    return archive_issue(key, archive_get)


def cached_rest_issue(repo: str, key: str, pr: str | int | None = None, raw_root: Path | None = None) -> Any:
    """A REST copy of the issue, with its changelog, saved earlier in eval/pool/raw/<repo>/<pr>/jira_<KEY>.json.

    The PR's own folder is tried first, then every other PR folder of the repo. Mail-archive copies are
    skipped. The copy is returned with source "jira_rest_cache" (and cache_path); None if there is none.
    """
    from jira_archive import CACHE_SOURCE, REST_LIKE, issue_source

    raw = (raw_root or EVAL / "pool" / "raw") / repo
    paths = ([raw / str(pr) / f"jira_{key}.json"] if pr is not None else []) + sorted(raw.glob(f"*/jira_{key}.json"))
    for path in paths:
        if not path.is_file():
            continue
        try:
            issue = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if issue_source(issue) in REST_LIKE and isinstance((issue.get("changelog") or {}).get("histories"), list):
            return issue | {"source": CACHE_SOURCE, "cache_path": path.relative_to(raw.parent).as_posix()}
    return None


def jira_issue_for(cfg: dict[str, Any], key: str, pr: str | int | None = None) -> Any:
    """The issue from a cached REST copy if one exists (source jira_rest_cache), else from Jira or the archive."""
    return cached_rest_issue(cfg["name"], key, pr) or jira_issue(cfg["jira_base"], key)


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
