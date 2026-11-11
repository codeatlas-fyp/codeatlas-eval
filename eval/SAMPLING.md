# Sampling record (FYP-1 pilot)

Status: v1 draft, 11 Nov 2026. Basis: FYP-1 Final Build Plan (10 Nov 2026), Part C; supervisor's dataset guide (5 Nov 2026).
Any change after the sample is drawn is logged under "Changes" with date and reason.

## Repositories and windows

Filled after each acceptance test (`scripts/repo_acceptance.py`, results in `eval/results/acceptance_<repo>.md`).
Accept a repo with at least 40 keyed, reviewed, merged PRs in the window.

| Repo | Jira project | Analysis root | Window | Keyed merged PRs | CODEOWNERS in window | Accepted |
|---|---|---|---|---|---|---|
| apache/airflow | AIRFLOW | whole repo | | | | |
| apache/arrow | ARROW | python/ | | | | |
| apache/libcloud | LIBCLOUD | whole repo | | | | |
| apache/spark (backup) | SPARK | python/pyspark/ | | | | |
| apache/beam (backup) | BEAM | sdks/python/ | | | | |

## Inclusion rules (fixed before any run)

1. Merged (or script-merged) inside the repository's window.
2. Changes at least one `.py` file under the analysis root.
3. Changes at most 20 files.
4. Not a bot PR (dependency bumps, release automation).
5. Jira key in the title, branch, body or a commit message, except for the `no_key` category.
6. Related PRs (a revert and its original, a follow-up fix) form one case group; a PR counts once.

## Categories and targets

Assigned from source metadata only, never from CodeAtlas output. Actual counts after labelling are reported.

| Category | Target | Source signal |
|---|---|---|
| supported_approval | 6 | Keyed; approval on the head commit by a listed CODEOWNER, or no rule applies; issue unchanged after work began |
| ownership_gap | 5 | Owner is a team whose membership at the cutoff is not visible, or approval only on an older commit |
| meaningful_link | 5 | Issue text names behaviour that clearly maps to changed functions (set by hand) |
| semantic_no_match | 4 | Key present but no changed entity relates to the issue text (set by hand) |
| requirement_changed | 2 | Summary or description edited after the first commit's time |
| no_key | 2 | Merged Python PR with no Jira key anywhere |
| **Total** | **24** | 8 per repository |

## Seed and procedure

- Seed: 20261114.
- `scripts/build_pool.py` writes `eval/pool/<repo>_pool.csv`; excluded rows keep their reason.
- Rows marked `needs_manual` are set by hand to `meaningful_link` or `semantic_no_match` before sampling.
- `scripts/sample_cases.py` draws per category (rarest first), at most 8 per repo, and writes `eval/cases.csv`
  and `eval/results/sampling_report.md`.
- Case IDs: AF-01 to AF-08 (Airflow), AR-01 to AR-08 (Arrow), LC-01 to LC-08 (Libcloud), CH-01 onwards (challenge).

## Labelling batches

| Batch | Labeller A | Labeller B | Adjudicator |
|---|---|---|---|
| 1: Airflow (AF-01 to AF-08) | Yusra | Areej | Saleha |
| 2: Arrow (AR-01 to AR-08) | Areej | Saleha | Yusra |
| 3: Libcloud (LC-01 to LC-08) | Saleha | Yusra | Areej |

## Shortfalls

Copied from `eval/results/sampling_report.md` after the draw.

## Changes

| Date | Change | Reason | Agreed by |
|---|---|---|---|
