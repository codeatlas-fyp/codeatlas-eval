"""Pin a merged PR to the Git history as it stood at the merge (integrity fix A1).

The GitHub API's `base.sha` is the base branch tip when the PR was last updated, and for a PR that is
still being looked at later it can move with the main branch. It is kept only "for comparison"
(`api_base_sha`, `api_head_sha`). The refs used for evidence come from the merge commit itself:

- two parents (GitHub merge button, "Merge pull request #N"): base_at_merge = 1st parent,
  head_at_merge = 2nd parent, merge_strategy = "merge";
- one parent (squash, rebase, or an Apache merge script such as merge_spark_pr.py):
  base_at_merge = the parent, head_at_merge = the PR head from `git fetch origin pull/<n>/head`,
  merge_strategy = "single_parent".

merge_base_sha = `git merge-base base_at_merge head_at_merge`. The result is checked: the files changed
between merge_base and head_at_merge (and, for single_parent, between the parent and the merge commit)
must be exactly the PR's file list. Equal -> historical_diff_status "verified"; anything else ->
"unverifiable" with a reason. Nothing is guessed.

A matching file list shows the right files changed, not that they changed the same way. The content check
compares, file by file, the PR's own change (merge_base..head_at_merge) with the change that reached the main
branch (base_at_merge..merge_commit): `git diff -U0` piped to `git patch-id --stable`, so only the added and
removed lines count (not line numbers or context, which move when the base branch moved). Binary files are
compared by their blob at head_at_merge and at merge_commit.

- historical_content_status "identical": every PR file changed in exactly the same way on the main branch;
- "differs": at least one file landed differently (a conflict resolved in the merge, a change edited by the
  merge script, an extra fix-up), listed in historical_content_reason. Such a case needs a manual look
  before it is scored;
- "not_checked": the file list was not verified, or Git could not produce the diffs.

Usage (one PR, by hand):
    python scripts/history.py --repo airflow --merge-commit <sha> --pr 6216
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from common import git

HISTORY_FIELDS = ["merge_commit_sha", "merge_strategy", "base_at_merge", "head_at_merge", "merge_base_sha",
                  "historical_diff_status", "historical_diff_reason", "historical_content_status",
                  "historical_content_reason", "api_base_sha", "api_head_sha"]


def parents(repo_dir: Path, sha: str) -> list[str]:
    """Parents of a commit, in order (git rev-list --parents -n 1)."""
    return git(repo_dir, "rev-list", "--parents", "-n", "1", sha).split()[1:]


def changed_files(repo_dir: Path, a: str, b: str) -> set[str]:
    """Paths changed from a to b. No rename detection: a rename lists both the old and the new path."""
    out = git(repo_dir, "diff", "--name-only", "--no-renames", a, b)
    return {line for line in out.splitlines() if line}


def pr_file_set(files: list[dict[str, Any]]) -> set[str]:
    """The PR's file list (GitHub pulls/<n>/files) in the same form: renames give both paths."""
    out: set[str] = set()
    for f in files:
        out.add(f["filename"])
        if f.get("previous_filename"):
            out.add(f["previous_filename"])
    return out


def fetch_pr_heads(repo_dir: Path, numbers: list[int | str]) -> None:
    """Fetch refs/pr/<n> for many PRs in one call (best effort; pin() checks each ref itself)."""
    specs = [f"pull/{n}/head:refs/pr/{n}" for n in numbers]
    for i in range(0, len(specs), 200):
        git(repo_dir, "fetch", "--quiet", "--no-tags", "origin", *specs[i:i + 200], check=False)


def pr_head(repo_dir: Path, number: int | str, fetch: bool = True) -> str | None:
    """SHA of the PR head (refs/pr/<n>), fetching it from origin first unless fetch is False."""
    if fetch:
        git(repo_dir, "fetch", "--quiet", "--no-tags", "origin", f"pull/{number}/head:refs/pr/{number}", check=False)
    sha = git(repo_dir, "rev-parse", "--verify", "--quiet", f"refs/pr/{number}^{{commit}}", check=False).strip()
    return sha or None


def _diff_problem(label: str, got: set[str], want: set[str]) -> str:
    extra, missing = sorted(got - want), sorted(want - got)
    parts = []
    if extra:
        parts.append(f"{len(extra)} extra (e.g. {extra[0]})")
    if missing:
        parts.append(f"{len(missing)} missing (e.g. {missing[0]})")
    return f"{label} differs from the PR file list: " + ", ".join(parts)


def _patch_id(repo_dir: Path, a: str, b: str, path: str) -> str:
    """patch-id of the change to one path from a to b, counting only added and removed lines ('' if none)."""
    diff = git(repo_dir, "diff", "-U0", "--no-renames", "--no-color", "--no-ext-diff", a, b, "--", path)
    if not diff.strip():
        return ""
    if "\nBinary files " in "\n" + diff or "\nGIT binary patch" in "\n" + diff:
        return "binary:" + git(repo_dir, "rev-parse", "--verify", "--quiet", f"{b}:{path}", check=False).strip()
    res = subprocess.run(["git", "-C", str(repo_dir), "patch-id", "--stable"], input=diff, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"git patch-id failed: {res.stderr.strip()}")
    return res.stdout.split()[0] if res.stdout.strip() else ""


def content_check(repo_dir: Path, merge_base: str, head: str, base: str, merge_commit: str,
                  paths: set[str]) -> tuple[str, str]:
    """(historical_content_status, reason): does every PR path change the same way on the main branch?"""
    differ = []
    try:
        for path in sorted(paths):
            if _patch_id(repo_dir, merge_base, head, path) != _patch_id(repo_dir, base, merge_commit, path):
                differ.append(path)
    except RuntimeError as e:
        return "not_checked", f"git error: {e}"
    if differ:
        more = f" and {len(differ) - 3} more" if len(differ) > 3 else ""
        return "differs", (f"{len(differ)} of {len(paths)} files landed differently on the main branch: "
                           + ", ".join(differ[:3]) + more)
    return "identical", f"all {len(paths)} files changed the same way on the main branch"


def pin(repo_dir: Path, merge_commit: str, pr_number: int | str, pr_files: list[dict[str, Any]],
        api_base: str = "", api_head: str = "", fetch: bool = True) -> dict[str, str]:
    """Historical refs for one merged PR. Never raises for a Git problem: it becomes 'unverifiable'."""
    out = dict.fromkeys(HISTORY_FIELDS, "")
    out.update(merge_commit_sha=merge_commit, api_base_sha=api_base, api_head_sha=api_head,
               historical_diff_status="unverifiable", historical_content_status="not_checked",
               historical_content_reason="the file list was not verified")
    try:
        ps = parents(repo_dir, merge_commit)
    except RuntimeError as e:
        out["historical_diff_reason"] = f"merge commit not readable: {e}"
        return out
    if len(ps) == 2:
        out.update(merge_strategy="merge", base_at_merge=ps[0], head_at_merge=ps[1])
    elif len(ps) == 1:
        out.update(merge_strategy="single_parent", base_at_merge=ps[0])
        head = pr_head(repo_dir, pr_number, fetch=fetch)
        if not head:
            out["historical_diff_reason"] = f"PR head pull/{pr_number}/head could not be fetched"
            return out
        out["head_at_merge"] = head
    else:
        out["merge_strategy"] = f"{len(ps)}_parents"
        out["historical_diff_reason"] = f"merge commit has {len(ps)} parents"
        return out

    try:
        out["merge_base_sha"] = git(repo_dir, "merge-base", out["base_at_merge"], out["head_at_merge"]).strip()
        want = pr_file_set(pr_files)
        problems = []
        got = changed_files(repo_dir, out["merge_base_sha"], out["head_at_merge"])
        if got != want:
            problems.append(_diff_problem("merge_base..head_at_merge", got, want))
        if out["merge_strategy"] == "single_parent":
            got = changed_files(repo_dir, out["base_at_merge"], merge_commit)
            if got != want:
                problems.append(_diff_problem("parent..merge_commit", got, want))
    except RuntimeError as e:
        out["historical_diff_reason"] = f"git error: {e}"
        return out
    if problems:
        out["historical_diff_reason"] = "; ".join(problems)
        return out
    out["historical_diff_status"] = "verified"
    out["historical_content_status"], out["historical_content_reason"] = content_check(
        repo_dir, out["merge_base_sha"], out["head_at_merge"], out["base_at_merge"], merge_commit, want)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from common import ensure_clone, gh, repo_cfg

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--merge-commit", required=True)
    ap.add_argument("--pr", required=True)
    a = ap.parse_args(argv)
    cfg = repo_cfg(a.repo)
    repo = ensure_clone(cfg, blobless=True)
    pr = gh(f"repos/{cfg['github']}/pulls/{a.pr}")
    files = gh(f"repos/{cfg['github']}/pulls/{a.pr}/files", paginate=True)
    print(json.dumps(pin(repo, a.merge_commit, a.pr, files, pr["base"]["sha"], pr["head"]["sha"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
