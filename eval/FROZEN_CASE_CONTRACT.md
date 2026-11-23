# Frozen-case evidence contract

What each file in a frozen case's `sources/` means, and which files describe the case **as it stood at the
decision cutoff** (the merge time). Anything that reads a frozen case — a labeller, the frozen-case runner in
CodeAtlas, a script — reads the state at the cutoff only from the files marked "at cutoff". A file marked
"as fetched" holds what the API returned on the freeze date; its current fields are never the state at the
cutoff. Missing history is marked as missing, never filled from the state as fetched.

Version: freeze_case.py 4 (21 Nov 2026).

## Files

| File | Describes | How the state at the cutoff is obtained | When it cannot be |
|---|---|---|---|
| `history.json` | Pinned commits: base and head at the merge, merge base, merge commit | Git objects (immutable); file list and content checked (`historical_diff_status`, `historical_content_status`) | `unverifiable` / `not_checked` with a reason; the case is not scored |
| `commits.json` | The PR's commits | Commit SHAs and their times are immutable | — |
| `files.json` | The PR's changed files | Checked against the pinned commits (history.json) | As above |
| `reviews.json` | Reviews submitted **at or before** the cutoff | Split by `submitted_at` at freeze time | — |
| `reviews_post_cutoff.json` | Reviews after the cutoff | Kept apart; **never used** for any rule | — |
| `timeline.json` | PR events with times (renames, labels, merges) | Read only events at or before the cutoff | `timeline.INACCESSIBLE.txt`: title at merge unknown, title keys stay uncertain |
| `jira_links.json` | Each key, where it was found, its link status, and the PR title at the merge | Title rebuilt from the timeline's rename events | Title `null`: keys found only in the title are uncertain |
| `CODEOWNERS_at_base.txt` | CODEOWNERS at the base commit | Read from Git at the base | Text `NO CODEOWNERS FILE AT BASE` means verified absent at that commit |
| `effective_policy.yaml` | The exact policy bytes the case was frozen under | Copied and checksummed (`policy_sha256`) | Freeze refuses without a policy |
| `jira_<KEY>_at_cutoff.txt` | Summary and description **at the cutoff** | REST copy: later edits undone with their old values. Archive: created text plus edits up to the cutoff | `reconstruction_status` `unverifiable` or `inaccessible`: no text given; `created_text_only`: text known, edit history unknown |
| `jira_<KEY>_state_at_cutoff.json` | Status, priority, assignee and resolution **at the cutoff**, with every change up to it (time, author, from, to) | REST copy: later changes undone, newest first, using each change's old value | Per field: `unverifiable` (changelog incomplete, or a change has no old value) or `unavailable` (source has no history of the field); `value` is then `null` |
| `pr.json` | The PR **as fetched** | — | Title, body, labels and state are today's. Use `jira_links.json` for the title at the merge. GitHub keeps no history of body edits, so the body at the merge cannot be verified |
| `jira_<KEY>.json` | The issue **as fetched**, with its changelog | — | Its `fields` (status, priority, assignee, resolution, summary, description) are the state when fetched. Never read them as the state at the cutoff |
| `fetched_at.txt` | When the freeze ran | — | — |

## Jira state: what can and cannot be rebuilt

| Source | Status, priority, assignee, resolution at the cutoff | Status category |
|---|---|---|
| REST cache (`jira_rest_cache`, Arrow and Spark pools) | Rebuilt from the changelog when it is complete; each change keeps its time and author | Not rebuilt |
| Mail archive (`apache_mail_archive`, Airflow) | Unavailable: the archive emails carry no status or priority history and no complete assignee history | Not rebuilt |
| Inaccessible key | Unavailable | Not rebuilt |

**Status category is never rebuilt.** Jira's categories (To Do, In Progress, Done) come from the current workflow
configuration, not from a timestamped record, so mapping a 2019 or 2022 status name to a category would use
today's configuration. A rule that needs a category must work from the status name at the cutoff and say which
mapping it applied, or report insufficient evidence.

**Completeness.** A changelog whose `total` is larger than the number of histories it holds is incomplete; every
field is then `unverifiable`. A copy that records no `total` is rebuilt, with `changelog_complete: null` (unknown),
and `scripts/check_jira_state.py` counts how many copies rely on that. If any do, the team checks a sample of
them against the archive emails before scoring rules that use the state.

## Checking it on the real data

On the machine with `eval/pool/raw/`:

```
python scripts/check_jira_state.py
```

It rebuilds the four fields for every included pool PR and key at the PR's merge time and writes
`eval/results/jira_state_check.md`: per repository and field, how many were reconstructed, unverifiable or
unavailable, and why.

## For the frozen-case runner

1. Read requirement text only from `jira_<KEY>_at_cutoff.txt` (after the `---` line), and Jira state only from
   `jira_<KEY>_state_at_cutoff.json`.
2. A field whose `reconstruction` is not `reconstructed` is missing evidence: the rule that needs it reports
   INSUFFICIENT_EVIDENCE with the file's `note`, never a value from `jira_<KEY>.json` or from live Jira.
3. Use `reviews.json`, never `reviews_post_cutoff.json`; timeline events only up to the cutoff.
4. Never call the live GitHub or Jira APIs for a frozen case.

## Effect on rule scope

`eval/rules_scope.yaml` marks C3, C4 and C8 not estimable on real data. With the state file, the Arrow and Spark
cases may carry assignee and priority histories with times (C4, C8). C3 still needs an approval status that
Apache's Jira workflows do not have. Whether C4 and C8 become estimable on those cases is a team decision taken
after `check_jira_state.py` has run on the real cache, before any labelling, and recorded in the scope file.
