# Repository acceptance: summary and proposed windows

Run by Yusra on 17 Nov 2026 on branch `feature/repo-acceptance-yusra` (git history only; no GitHub or Jira
API calls). Per-repo details are in `acceptance_<repo>.md` next to this file. These are proposals for the
dataset lead to confirm; `eval/repos.json` and `eval/SAMPLING.md` are not changed by this branch.

## Result

| Repo | Role in repos.json | Window tested | Merged PRs | Keyed merged PRs | Keyed PRs touching .py under the analysis root | CODEOWNERS in window | Result |
|---|---|---|---|---|---|---|---|
| apache/airflow | main | 2019-10-01 to 2019-12-31 | 548 | 446 | 409 | none | ACCEPT |
| apache/arrow (`python/`) | main | 2022-04-01 to 2022-06-30 | 576 | 515 | 76 | none | ACCEPT |
| apache/libcloud | main | 2016-01-01 to 2019-12-31 | 247 | 18 | not counted | none | REJECT |
| apache/spark (`python/pyspark/`) | backup | 2022-04-01 to 2022-06-30 | 712 | 696 | 121 | none | ACCEPT |
| apache/beam (`sdks/python/`) | backup | 2021-04-01 to 2021-06-30 | 537 | 432 | 147 | none | ACCEPT |

Threshold: at least 40 keyed, merged PRs in the window. Review share and Jira readability still need the
by-hand check of the 5 sampled PRs listed in each per-repo file (or `--check-reviews` with a token).

## Findings

1. **Libcloud fails in every window tried.** 2013-2015: 16 keyed PRs; 2016-2019: 18; 2018-2019: 8 (all
   counted with the fix in finding 2). Its commits stop carrying LIBCLOUD keys in 2020. Proposal: replace it with the first
   backup, Spark (still on Jira today, large PySpark share), and keep Beam as the spare.
2. **PR numbers were being missed.** `pr_number` only read the commit subject. The Apache merge scripts
   (Airflow before mid-2018, Arrow before 2022, Libcloud) keep the Jira title as the subject and put the PR
   in the body as `Closes #9618 from user/branch`. With the body line read as well, Arrow 2019 goes from
   13 to 2,270 keyed merged PRs and Airflow 2018 from 408 to 920. Fixed in `scripts/common.py`
   (`pr_number(subject, body)`); `build_pool.py` and `repo_acceptance.py` pass the body.
3. **No repository has CODEOWNERS while it used Jira.** Airflow added `.github/CODEOWNERS` on 2021-02-16
   (its AIRFLOW keys stop around April 2020). Arrow added it on 2023-01-16 (ARROW keys stop that month,
   replaced by GH-n). Beam had a root CODEOWNERS for 12 days in July 2018. Libcloud and Spark have none.
   So rule C5 (code owner approval) will be NOT_APPLICABLE on every pilot case, and its evidence has to
   come from the challenge set (sandbox or constructed cases). The team should decide this knowingly.
4. **Windows are three months on purpose.** `build_pool.py` makes about four GitHub API calls per PR; a
   500 to 700 PR window stays inside the 5,000 calls per hour limit. A full year of Airflow 2019 has 1,875
   merged PRs.

## Proposed `window` values for eval/repos.json

| Repo | since | until |
|---|---|---|
| airflow | 2019-10-01 | 2019-12-31 |
| arrow | 2022-04-01 | 2022-06-30 |
| spark (promote to main) | 2022-04-01 | 2022-06-30 |
| beam (spare) | 2021-04-01 | 2021-06-30 |
