"""Build the candidate pool for one repository (build plan C5 step 1, C6 pool columns).

Usage:
    python scripts/build_pool.py --repo libcloud            # uses the window in eval/repos.json
    python scripts/build_pool.py --repo airflow --jira      # also reads Jira to flag edited requirements
    python scripts/build_pool.py --repo airflow --limit 50  # stop after 50 new PRs (resumable)

Writes eval/pool/<repo>_pool.csv. Every candidate PR gets a row; excluded rows keep their reason
(rows are never deleted). Raw API responses are cached in eval/pool/raw/ (git-ignored).
The provisional category comes from source metadata only, never from CodeAtlas output. Rows marked
needs_manual are set by hand to meaningful_link or semantic_no_match after reading the issue and diff.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from common import (EVAL, codeowners_at, dump_json, ensure_clone, find_keys, first_parent_commits, gh, is_team, jira_issue,
                    merged_branch_messages, owners_for, parse_codeowners, pr_number, read_csv, repo_cfg, write_csv)

FIELDS = ["repo", "pr_number", "pr_url", "merged_at", "base_sha", "head_sha", "merge_commit_sha", "title", "keys_found",
          "key_locations", "py_files_changed", "files_changed", "review_count", "approvals_on_head", "codeowners_present",
          "provisional_category", "included", "exclusion_reason"]
MAX_FILES = 20
BOT_TITLE = re.compile(r"^\s*(bump |build\(deps|chore\(deps|\[?release\b|prepare release|update changelog)", re.IGNORECASE)


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def requirement_edited(cfg: dict[str, Any], keys: list[str], work_began: str, merged_at: str, raw_dir: Path) -> bool | None:
    """True if a summary/description edit happened after the first commit and before the merge."""
    edited = False
    for key in keys:
        try:
            issue = jira_issue(cfg["jira_base"], key)
        except Exception as e:  # noqa: BLE001 - record, do not guess
            print(f"  jira {key}: {e}")
            return None
        dump_json(raw_dir / f"jira_{key}.json", issue)
        for h in issue.get("changelog", {}).get("histories", []):
            at = ts(h["created"].replace("+0000", "+00:00"))
            if ts(work_began) < at <= ts(merged_at) and any(i.get("field") in ("summary", "description") for i in h.get("items", [])):
                edited = True
    return edited


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jira", action="store_true")
    a = ap.parse_args()

    cfg = repo_cfg(a.repo)
    since = a.since or cfg["window"]["since"]
    until = a.until or cfg["window"]["until"]
    if not (since and until):
        raise SystemExit("set the window in eval/repos.json or pass --since/--until")
    repo = ensure_clone(cfg)
    out = EVAL / "pool" / f"{cfg['name']}_pool.csv"
    rows = read_csv(out)
    done = {r["pr_number"] for r in rows}
    root = cfg["analysis_root"]
    new = 0

    for c in first_parent_commits(repo, since, until):
        n = pr_number(c["subject"])
        if n is None or str(n) in done:
            continue
        if a.limit and new >= a.limit:
            break
        new += 1
        raw = EVAL / "pool" / "raw" / cfg["name"] / str(n)
        pr = gh(f"repos/{cfg['github']}/pulls/{n}")
        files = gh(f"repos/{cfg['github']}/pulls/{n}/files", paginate=True)
        reviews = gh(f"repos/{cfg['github']}/pulls/{n}/reviews", paginate=True)
        commits = gh(f"repos/{cfg['github']}/pulls/{n}/commits", paginate=True)
        for name, data in (("pr", pr), ("files", files), ("reviews", reviews), ("commits", commits)):
            dump_json(raw / f"{name}.json", data)

        # keys and where they were found
        where: dict[str, set[str]] = {}
        sources = {"title": pr.get("title", ""), "branch": pr.get("head", {}).get("ref", ""), "body": pr.get("body") or "",
                   "commit": "\n".join(x["commit"]["message"] for x in commits) + "\n" + c["body"] + "\n" + merged_branch_messages(repo, c)}
        for loc, text in sources.items():
            for k in find_keys(text, cfg["key_regex"]):
                where.setdefault(k, set()).add(loc)
        keys = sorted(where)

        paths = [f["filename"] for f in files]
        py = [p for p in paths if p.endswith(".py") and p.startswith(root)]
        head = pr["head"]["sha"]
        base = pr["base"]["sha"]
        approvals = [r for r in reviews if r.get("state") == "APPROVED"]
        approvers_on_head = {r["user"]["login"].lower() for r in approvals if r.get("commit_id") == head and r.get("user")}

        co_path, co_text = codeowners_at(repo, base)
        rules = parse_codeowners(co_text) if co_text else []
        owner_sets = [owners_for(p, rules) for p in py] if rules else []
        matched = [o for o in owner_sets if o]
        user_owners = {o.lstrip("@").lower() for os_ in matched for o in os_ if not is_team(o) and o.startswith("@")}
        all_team = bool(matched) and all(all(is_team(o) for o in os_) for os_ in matched)

        # inclusion rules (C4)
        login = (pr.get("user") or {}).get("login", "")
        reason = ""
        if not pr.get("merged_at"):
            reason = "not merged on GitHub (check script-merge)"
        elif not py:
            reason = f"no .py file under '{root or '/'}'"
        elif len(paths) > MAX_FILES:
            reason = f"{len(paths)} files changed (> {MAX_FILES})"
        elif login.endswith("[bot]") or (pr.get("user") or {}).get("type") == "Bot" or BOT_TITLE.search(pr.get("title", "")):
            reason = "bot or release PR"

        # provisional category from metadata only
        if not keys:
            cat = "no_key"
        elif a.jira and requirement_edited(cfg, keys, commits[0]["commit"]["committer"]["date"] if commits else pr["created_at"],
                                           pr["merged_at"] or pr["closed_at"], raw):
            cat = "requirement_changed"
        elif approvals and not approvers_on_head:
            cat = "ownership_gap"            # approval only on an older commit
        elif all_team:
            cat = "ownership_gap"            # owners are teams; membership at cutoff not visible
        elif approvers_on_head and (not matched or approvers_on_head & user_owners):
            cat = "supported_approval"
        else:
            cat = "needs_manual"             # set to meaningful_link or semantic_no_match by hand

        rows.append({
            "repo": cfg["name"], "pr_number": n, "pr_url": pr["html_url"], "merged_at": pr.get("merged_at") or "",
            "base_sha": base, "head_sha": head, "merge_commit_sha": c["sha"], "title": pr.get("title", ""),
            "keys_found": ";".join(keys), "key_locations": ";".join(f"{k}:{'+'.join(sorted(v))}" for k, v in sorted(where.items())),
            "py_files_changed": len(py), "files_changed": len(paths), "review_count": len(reviews),
            "approvals_on_head": len(approvers_on_head), "codeowners_present": co_path or "no",
            "provisional_category": cat, "included": "no" if reason else "yes", "exclusion_reason": reason,
        })
        write_csv(out, rows, FIELDS)   # write after every PR so a crash loses nothing
        print(f"#{n:<6} {cat:<20} {'excluded: ' + reason if reason else 'included'}")

    print(f"\n{len(rows)} rows in {out} ({new} new). Related PRs (revert + original, follow-up fix) must be grouped by hand.")


if __name__ == "__main__":
    main()
