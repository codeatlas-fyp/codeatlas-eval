# Dataset collection: work done on `feature/dataset-collection-yusra`

Author: Yusra. Date: 17 Nov 2026. Branch: `feature/dataset-collection-yusra`, made from
`feature/dataset-harness` at `4079ab1`. It has 23 commits and head `2ae4bb1`, and has not been merged yet.
This note is also copied onto `feature/dataset-harness`, so everyone working on the harness can see what
was done on the other branch.

Build plan Part C, steps C5.0 to C5.1 are done: repo acceptance and the candidate pools for all three repos.
Sampling (C5.2) and freezing (C5.3) have not started yet. No labels were written, and nothing here uses
CodeAtlas output (rule C8).

---

## 1. Summary

| Step | Status | Output |
|---|---|---|
| Repo acceptance (5 repos) | Done | `eval/results/acceptance_*.md`, `acceptance_summary.md` |
| Repo choice and windows | Done, team OK still needed for Spark replacing Libcloud | `eval/repos.json` |
| Candidate pools | Done for Airflow, Arrow, Spark | `eval/pool/{airflow,arrow,spark}_pool.csv` |
| "Requirement changed" flags | Done (from the mail archive) | `provisional_category` in the pools |
| Issue text check | Done | `eval/pool/{airflow,arrow,spark}_issues.csv` |
| `needs_manual` rows set by hand | **To do (people)** | pools |
| Sampling 24 cases | To do | `eval/cases.csv`, `eval/results/sampling_report.md` |
| Freezing evidence | To do | `eval/cases/<id>/` |

## 2. Repositories and windows

| Repo | Role | Window | Analysis root | Acceptance |
|---|---|---|---|---|
| Airflow | main | 2019-10-01 to 2019-12-31 | `/` | Accept (446 keyed PRs) |
| Arrow | main | 2022-04-01 to 2022-06-30 | `python/` | Accept (515 keyed PRs, 76 touch `python/*.py`) |
| Spark | **main (promoted from backup)** | 2022-04-01 to 2022-06-30 | `python/pyspark/` | Accept (696 keyed PRs) |
| Libcloud | **rejected** | none | `/` | Reject: only 18 keyed PRs in 2016 to 2019 |
| Beam | backup | 2021-04-01 to 2021-06-30 | `sdks/python/` | Accept (432 keyed PRs) |

**Team decision needed:** Spark replaces Libcloud as the third main repo.

## 3. Candidate pools (17 Nov 2026)

| Repo | PRs in window | Included | supported_approval | ownership_gap | requirement_changed | no_key | needs_manual |
|---|---|---|---|---|---|---|---|
| Airflow | 551 | 405 | 272 | 52 | 24 | 25 | 32 |
| Arrow | 579 | 75 | 46 | 15 | 3 | 3 | 8 |
| Spark | 716 | 125 | 82 | 24 | 11 | 3 | 5 |

Most exclusions are "no .py file under the analysis root": Airflow 116, Arrow 499, Spark 590. After those
comes "more than 20 files changed": Airflow 30, Arrow 5, Spark 1. No PR was excluded as a bot or
release PR.

Every sampling target (C4) has enough candidates. The tightest are `semantic_no_match` (4) and
`meaningful_link` (5), which come from the 45 `needs_manual` rows once people have set them.

### Issue text (from `issue_summary.py`)

| Repo | Issues | Title only | With a description |
|---|---|---|---|
| Airflow | 416 | 171 (41%) | 245 |
| Arrow | 77 | 5 | 72 |
| Spark | 134 | 33 | 101 |

A title-only issue gives the semantic part one short criterion to match. **Team decision needed:** should
sampling prefer Airflow cases that have a description?

## 4. Problems found and how they were fixed

1. **PR number not found in Apache merges.** Apache merge commits often say `Closes #N` in the body
   rather than `(#N)` in the subject. `common.pr_number()` now reads both.
2. **Apache Jira needs a login now.** `issues.apache.org` answers `401 Login Required` to every read,
   including the REST API and the browse page, and public sign-up is closed. But every Jira issue and
   every edit was also emailed to a public list (Airflow: `commits@`, Arrow and Spark: `issues@`), and
   those emails are kept at `lists.apache.org`. The new `scripts/jira_archive.py` rebuilds an issue from
   them: the "Created" email gives the summary and description, and the "Updated" emails give later
   summary and description edits with their times. The result has the same shape as the Jira REST API,
   so `build_pool.py` and `freeze_case.py` use it unchanged. `common.jira_issue()` tries Jira first, and
   after the first 401 it uses the archive. Each saved issue records `source` and `archive.list`.
   Checked by hand: AIRFLOW-5477 (no description, confirmed in the raw email) and ARROW-16000 (full
   description).
3. **Arrow and Spark PRs looked "not merged".** Both projects merge with a script
   (`merge_arrow_pr.py`, `merge_spark_pr.py`) that pushes the commit to the main branch and closes the
   PR. GitHub then leaves `merged_at` empty. `build_pool.py` now counts a closed PR whose commit is on
   the main branch's first-parent line as merged, with that commit's time as `merged_at`. The new column
   `merged_via` says `github` or `script (commit <sha> on main)`. Spark: all 716 are script merges.
   Arrow: 411 script and 132 GitHub. The other 36 Arrow rows have an empty `merged_via` because they
   were written before the column existed, and all of them were excluded for other reasons.
4. **Dropped connections.** GitHub sometimes closes a connection without answering. `common._get()`
   now retries that too, as well as rate limits and 5xx errors.
5. **No CODEOWNERS during the Jira era.** Airflow added CODEOWNERS on 2021-02-16 and Arrow on
   2023-01-16, both after their windows. So **C5 is NOT_APPLICABLE on all real pilot cases** and can
   only be tested on the challenge (sandbox) set. **Team decision needed** on how to report this.

## 5. Scripts added or changed on this branch

| File | What it does |
|---|---|
| `scripts/common.py` | `pr_number()` reads `Closes #N`; `jira_issue()` falls back to the archive; `archive_get()`; retries dropped connections |
| `scripts/jira_archive.py` (new) | Rebuilds a Jira issue from lists.apache.org. Check one by hand: `python scripts/jira_archive.py AIRFLOW-5477` |
| `scripts/build_pool.py` | Script merges count as merged (`merged_via`); reuses cached PR data in `eval/pool/raw/`; `--recheck-unmerged` |
| `scripts/repo_acceptance.py` | Same PR-number rule as the pool |
| `scripts/flag_requirement_changes.py` (new) | Marks pool rows whose issue summary or description was edited between the PR's first commit and its merge as `requirement_changed`. Resumable |
| `scripts/issue_summary.py` (new) | Writes `eval/pool/<repo>_issues.csv`: summary, description length, title-only flag |
| `scripts/freeze_case.py` | Also writes `sources/jira_<KEY>_at_cutoff.txt`: the issue text as it stood at the merge, ready for `prepare_case.py --issue-text` in the CodeAtlas repo |
| `tests/` (new) | 19 unit tests, standard library only: `python -m unittest discover -s tests -v` |

`eval/pool/raw/` (API caches) and `eval/repos/` (clones) stay local and are git-ignored. They are on
Yusra's PC.

## 6. How to repeat it

Run on a PC, not the cloud sandbox, because the GitHub API and lists.apache.org must be reachable.
You need a fine-grained GitHub token with public repositories, read-only.

```powershell
$env:CODEATLAS_GITHUB_TOKEN = "<token>"
uv run --no-project python -m unittest discover -s tests -v
uv run --no-project python scripts/build_pool.py --repo airflow      # repeat for arrow, spark
uv run --no-project python scripts/flag_requirement_changes.py --repo airflow
uv run --no-project python scripts/issue_summary.py --repo airflow
```
Runs save after every PR. If one stops, run the same command again and it carries on where it stopped.
The pools took about 1 hour per repo, plus the first clone.

## 7. Next steps

1. **People:** set each included `needs_manual` row to `meaningful_link` or `semantic_no_match`
   (Airflow 32, Arrow 8, Spark 5). Read the issue text and the PR diff, never CodeAtlas output.
   Edit `provisional_category` in `eval/pool/<repo>_pool.csv`.
2. Agree on the three team decisions above (Spark for Libcloud, C5 on real cases, title-only issues).
3. Sampling: `python scripts/sample_cases.py --repos airflow arrow spark` (seed 20261114).
4. Freezing: `python scripts/freeze_case.py --all`.
5. Labelling, blind A/B plus adjudication, per `eval/LABELLING_GUIDE.md`. Labels freeze on Sun 22 Nov.
