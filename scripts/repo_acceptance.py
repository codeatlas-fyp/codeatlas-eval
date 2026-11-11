"""Repository acceptance test (build plan C3): is this repo usable for the pilot in this window?

Usage:
    python scripts/repo_acceptance.py --repo airflow --since 2019-01-01 --until 2019-12-31
    python scripts/repo_acceptance.py --repo libcloud --since 2018-01-01 --until 2019-12-31 --check-reviews

Counts keyed, merged PRs on the main branch (first-parent), checks CODEOWNERS at the start and end of the
window, picks 5 random keyed PRs (seeded) to open in the browser, and writes eval/results/acceptance_<repo>.md.
Accept the repo if it has at least 40 keyed, reviewed, merged PRs in the window.
"""

from __future__ import annotations

import argparse
import random
from datetime import date

from common import (EVAL, codeowners_at, ensure_clone, find_keys, first_parent_commits, gh, git, merged_branch_messages,
                    pr_number, repo_cfg, default_branch)

THRESHOLD = 40


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--check-reviews", action="store_true", help="call the GitHub API for the 5 sampled PRs (needs a token)")
    ap.add_argument("--blobless", action="store_true", help="faster partial clone")
    a = ap.parse_args()

    cfg = repo_cfg(a.repo)
    repo = ensure_clone(cfg, blobless=a.blobless)
    commits = first_parent_commits(repo, a.since, a.until)
    prs, keyed = [], []
    for c in commits:
        n = pr_number(c["subject"])
        if n is None:
            continue
        text = f"{c['subject']}\n{c['body']}\n{merged_branch_messages(repo, c)}"
        keys = find_keys(text, cfg["key_regex"])
        prs.append((n, c, keys))
        if keys:
            keyed.append((n, c, keys))

    branch = default_branch(repo)
    start = git(repo, "rev-list", "-1", f"--before={a.since}", branch).strip()
    end = git(repo, "rev-list", "-1", f"--before={a.until}", branch).strip()
    co_start = codeowners_at(repo, start)[0] if start else None
    co_end = codeowners_at(repo, end)[0] if end else None

    rng = random.Random(a.seed)
    sample = rng.sample(keyed, min(5, len(keyed)))
    lines = [
        f"# Acceptance test: {cfg['github']}",
        "",
        f"Run on {date.today().isoformat()}; window {a.since} to {a.until}; branch {branch}; seed {a.seed}.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| First-parent commits in window | {len(commits)} |",
        f"| Merged PRs (PR number in subject) | {len(prs)} |",
        f"| Keyed merged PRs ({cfg['jira_project']}-n anywhere in the merge or its commits) | {len(keyed)} |",
        f"| CODEOWNERS at window start | {co_start or 'none'} |",
        f"| CODEOWNERS at window end | {co_end or 'none'} |",
        f"| Analysis root | {cfg['analysis_root'] or '(whole repo)'} |",
        "",
        "## 5 random keyed PRs to open by hand",
        "",
        "| PR | Keys | Merged | Reviews (API) | Approvals | Jira readable? (by hand) |",
        "|---|---|---|---|---|---|",
    ]
    reviewed = 0
    for n, c, keys in sample:
        rev, appr = "", ""
        if a.check_reviews:
            reviews = gh(f"repos/{cfg['github']}/pulls/{n}/reviews", paginate=True)
            rev = str(len(reviews))
            appr = str(sum(1 for r in reviews if r.get("state") == "APPROVED"))
            reviewed += 1 if reviews else 0
        jira = ", ".join(f"[{k}]({cfg['jira_base']}/browse/{k})" for k in keys)
        lines.append(f"| [#{n}](https://github.com/{cfg['github']}/pull/{n}) | {jira} | {c['time'][:10]} | {rev} | {appr} | |")
    lines += ["", "## Decision", ""]
    if a.check_reviews and sample:
        est = round(len(keyed) * reviewed / len(sample))
        lines.append(f"Reviewed share in sample: {reviewed}/{len(sample)}; estimated keyed and reviewed PRs: about {est}.")
    verdict = "ACCEPT" if len(keyed) >= THRESHOLD else "REJECT or widen the window"
    lines.append(f"Keyed merged PRs vs threshold {THRESHOLD}: {len(keyed)} -> {verdict} (confirm review share and Jira access by hand).")
    out = EVAL / "results" / f"acceptance_{cfg['name']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()
