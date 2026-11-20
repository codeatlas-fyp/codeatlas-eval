# Sampling record (FYP-1 pilot)

Status: v2 draft, 20 Nov 2026 (v1: 11 Nov 2026). Basis: FYP-1 Final Build Plan (10 Nov 2026), Part C; supervisor's
dataset guide (5 Nov 2026); repository acceptance runs (`eval/results/acceptance_summary.md`, 17 Nov 2026); team
decisions B1 to B5 and Part C of the integrity fixes (`eval/results/dataset_integrity_fixes.md`, 20 Nov 2026).
Any change after the sample is drawn is logged under "Changes" with date and reason.

## Repositories and windows

From `scripts/repo_acceptance.py` (results in `eval/results/acceptance_<repo>.md`). Accept a repo with at least
40 keyed, reviewed, merged PRs in the window. Windows are three months so a pool stays inside the GitHub rate
limit.

| Repo | Role | Jira project | Analysis root | Window | Keyed merged PRs | CODEOWNERS in window | Decision |
|---|---|---|---|---|---|---|---|
| apache/airflow | main | AIRFLOW | whole repo | 2019-10-01 to 2019-12-31 | 446 | none | accepted |
| apache/arrow | main | ARROW | python/ | 2022-04-01 to 2022-06-30 | 515 | none | accepted |
| apache/spark | main (promoted from backup) | SPARK | python/pyspark/ | 2022-04-01 to 2022-06-30 | 696 | none | accepted |
| apache/libcloud | rejected | LIBCLOUD | whole repo | 2016-01-01 to 2019-12-31 | 18 | none | rejected: 18 keyed PRs, below 40 in every window tried |
| apache/beam | backup | BEAM | sdks/python/ | 2021-04-01 to 2021-06-30 | 432 | none | spare, used only if a main repo fails |

No window has a CODEOWNERS file, so C5 is not estimable on the pilot (`eval/rules_scope.yaml`) and is tested on
the challenge set (`eval/challenge/README.md`).

## Inclusion rules (fixed before any run)

1. Merged (or script-merged) inside the repository's window.
2. Changes at least one `.py` file under the analysis root.
3. Changes at most 20 files.
4. Not a bot PR (dependency bumps, release automation).
5. Jira key in the title, branch, body or a commit message, except for the `no_key` category.
6. Related PRs (a revert and its original, a follow-up fix) form one case group; a PR counts once.

## Categories and quotas

Assigned from source metadata only, never from CodeAtlas output (`scripts/build_pool.py`). These are sampling
categories, not labels: actual results after labelling are reported separately. Only approvals submitted at or
before the merge count (fix A4).

**Quotas: proposed, pending team approval.**

| Category | Quota | Source signal |
|---|---|---|
| supported_approval | 7 | Keyed; approval on the head commit at or before the merge by a listed CODEOWNER, or no CODEOWNERS rule applies; issue unchanged during the PR |
| ownership_gap | 6 | Approval only on an older commit, or owners are teams whose membership at the cutoff is not visible |
| no_approval | 7 | Keyed PR with no approval on the head commit at or before the merge |
| requirement_changed | 2 | Summary or description edited after the first commit and before the merge |
| no_key | 2 | Merged Python PR with no Jira key anywhere |
| **Total** | **24** | exactly 8 per repository |

`no_approval` replaces the former hand-set category (decision B1). Whether an issue's criteria match the code,
including the no-match case, is no longer a sampling category: it is an annotator's judgement, and no-match is
evaluated on the challenge set (CH-11), not on the real pilot.

## Seed and procedure

- Seed: 20261114.
- `scripts/build_pool.py` writes `eval/pool/<repo>_pool.csv`; excluded rows keep their reason. Existing pools are
  brought up to date with `scripts/update_pool.py --history --reviews --links --quality`.
- `scripts/sample_cases.py` (defaults: airflow, arrow, spark):
  1. a deterministic backtracking search over the repo x category count matrix meets every quota and the 8 per
     repo when the pool allows it; otherwise it takes the allocation with the most cases and the report lists
     every shortfall with its reason (never silently underfilled);
  2. inside each cell, a seeded random choice after a preference order: `link_status` verified first, then
     `requirement_quality` explicit_criteria or descriptive_issue over title_only, then `historical_diff_status`
     verified over unverifiable;
  3. writes `eval/cases.csv` and `eval/results/sampling_report.md`, which records the seed and the sha256 of each
     pool file, the quality mix, and per repo the cases with one key, several keys and at least one verified key.
- Case IDs: AF-01 to AF-08 (Airflow), AR-01 to AR-08 (Arrow), SP-01 to SP-08 (Spark), CH-01 onwards (challenge).
- The sample is drawn only after the team approves the quotas and the baseline policy (`eval/policies/README.md`).

## Labelling batches

| Batch | Labeller A | Labeller B | Adjudicator |
|---|---|---|---|
| 1: Airflow (AF-01 to AF-08) | Yusra | Areej | Saleha |
| 2: Arrow (AR-01 to AR-08) | Areej | Saleha | Yusra |
| 3: Spark (SP-01 to SP-08; was Libcloud) | Saleha | Yusra | Areej |

## Shortfalls

Copied from `eval/results/sampling_report.md` after the draw. A trial run on the pools of 20 Nov 2026 (not
written to `eval/cases.csv`) is in `eval/results/dataset_integrity_fixes.md`.

## Changes

| Date | Change | Reason | Agreed by |
|---|---|---|---|
| 17 Nov 2026 | Libcloud rejected; Spark promoted to main; Beam kept as backup | Libcloud has 18 keyed PRs (below 40) in every window | (to agree) |
| 20 Nov 2026 | Hand-set category replaced by no_approval; no-match moved to the challenge set; quotas 7/6/7/2/2 | Decisions B1 and Part C | (to agree) |
| 20 Nov 2026 | Allocation by backtracking with a shortfall table; preference order inside cells | The old greedy draw could underfill a feasible sample | (to agree) |
