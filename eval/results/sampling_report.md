# Sampling report

Seed 20261114; repos airflow, arrow, spark.

Pool files:

- `eval/pool/airflow_pool.csv` sha256 `b113f27569d8f0fa9448bc6b565518aa3b246ff4cd5f5d43ca09c0afcb45602f`
- `eval/pool/arrow_pool.csv` sha256 `549fee715d37801f889402bb36573203b1c89cb82c54c297c633a6e1b612169a`
- `eval/pool/spark_pool.csv` sha256 `61724671b4b866a185641a7d896232885db4435e8ae9ea1fe2cb8fa77bc5c9f5`

## Quotas (Dataset Plan (Final), 21 Nov 2026): 9 cases, 3 per repo

| Category | Quota |
|---|---|
| supported_approval | 3 |
| ownership_gap | 2 |
| no_approval | 2 |
| requirement_changed | 1 |
| no_key | 1 |

## Reverts excluded

Included pool rows left out because the PR is a revert (title starts with "Revert" after any Jira keys and [tags]):

| Repo | Reverts | PRs |
|---|---|---|
| airflow | 3 | #6222, #6357, #6783 |
| arrow | 0 | - |
| spark | 0 | - |

## Included pool rows per cell

| Repo | supported_approval | ownership_gap | no_approval | requirement_changed | no_key |
|---|---|---|---|---|---|
| airflow | 269 | 52 | 32 | 24 | 25 |
| arrow | 46 | 15 | 8 | 3 | 3 |
| spark | 82 | 24 | 5 | 11 | 3 |

## Allocation

| Repo | supported_approval | ownership_gap | no_approval | requirement_changed | no_key | Total |
|---|---|---|---|---|---|---|
| airflow | 1 | 1 | 1 | 0 | 0 | 3 |
| arrow | 1 | 1 | 1 | 0 | 0 | 3 |
| spark | 1 | 0 | 0 | 1 | 1 | 3 |
| total | 3 | 2 | 2 | 1 | 1 | 9 |

Total cases: 9 of 9.

## Shortfalls

None: every quota and every repo total is met.

## Related cases

Case groups applied (case_groups.csv): 0.

Sampled PRs that share a Jira key (decide whether each pair is one case group before the official draw; sharing a key alone does not make them one):

None.

## Requirement quality of the sampled cases

| Value | Cases |
|---|---|
| (none) | 1 |
| descriptive_issue | 8 |

## Link status of the sampled cases

| Value | Cases |
|---|---|
| (none) | 1 |
| verified | 8 |

## Historical diff status of the sampled cases

| Value | Cases |
|---|---|
| verified | 9 |

## Historical content status of the sampled cases

| Value | Cases |
|---|---|
| identical | 9 |

## Jira keys per repo (sampled cases)

| Repo | One key | Several keys | At least one verified key |
|---|---|---|---|
| airflow | 3 | 0 | 3 |
| arrow | 2 | 1 | 3 |
| spark | 2 | 0 | 2 |

## Requirement not proven unchanged (edit history unknown)

Rows with a created_text_only key: C1 and C6 stay INSUFFICIENT_EVIDENCE for them (eval/scoring_rules.md), and their category cannot be proven to be 'unchanged'.

| Repo | Sampled cases | Cases |
|---|---|---|
| airflow | 0 | - |
| arrow | 0 | - |
| spark | 0 | - |

## Rare case (governance file changed; reported separately, never pooled with the draw)

Seeded order fixed before the draw: arrow #12672, airflow #6949, airflow #6702, airflow #6681, airflow #6563.

Chosen: AR-R01 = arrow #12672 (ownership_gap).
