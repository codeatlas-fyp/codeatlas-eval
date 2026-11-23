# Pilot preparation after the audit of 21 Nov 2026

What changed in the dataset tools after the Day 1-2 audit, and what was checked on real data. Commits on
`feature/dev-pilot-prep`.

## Changes

| Audit point | Change | Where |
|---|---|---|
| 2. History content | `historical_content_status` (identical / differs / not_checked): `git patch-id --stable` of the PR's change to each file vs the change that landed on the main branch | `scripts/history.py`, pool columns, `case.yaml` |
| 3. Policy snapshot | exact policy bytes frozen as `sources/effective_policy.yaml`, in the manifest; `--verify` checks it against `policy_sha256` | `scripts/freeze_case.py` |
| 1. Sign-off before labels | a scored case does not freeze under a DRAFT policy (dev cases and `--allow-draft` excepted) | `scripts/freeze_case.py` |
| 10. No silent label carry-over | `--refresh` writes `LABELS_STALE.txt` when carried labels were made on other evidence or policy; `--verify` reports it | `scripts/freeze_case.py` |
| 4. Related cases | `eval/case_groups.csv`; one PR per group in the draw; shared Jira keys reported | `scripts/case_groups.py`, `scripts/sample_cases.py` |
| 5. Dev cases | `eval/dev_cases.csv`, `eval/dev_cases/`; candidates, add, overlap check | `scripts/dev_cases.py` |
| 7, 8. Neutral packets | header stripped, one `prepare_case.py` run per key, criteria merged, one entity list, `PACKET.json` | `scripts/prepare_packets.py` |

Tests: 167 (`python -m unittest discover -s tests`), all passing; `audit_private.py`: 0 problems.

## Checked on real data (21 Nov)

Blobless clones of apache/airflow, apache/arrow and apache/spark; pool rows of 20 Nov.

**Content check, every included row with a verified file list (603):**

| Repository | Rows | identical | differs |
|---|---|---|---|
| Airflow | 403 | 400 | 3 |
| Arrow | 75 | 74 | 1 |
| Spark | 125 | 125 | 0 |

The four `differs` rows were inspected by hand; each is a real difference:

- airflow #6369 and #6529: stacked PRs ("depends on AIRFLOW-..."); the PR branch carried a change that landed
  separately, so the main branch received a different change to the same file.
- airflow #6355: an import line in a test file landed differently (conflict resolution).
- arrow #13109: one blank line differs in a test file.

None is in the trial draw. These numbers are from a check run here, not yet in the pool files: run
`python scripts/update_pool.py --repo <name> --history` on the machine with the pools to fill the two new pool
columns (about 2-3 s per PR on a blobless clone: the blobs of each PR are fetched in one request).

**Packets:** `prepare_packets.py` with the real `prepare_case.py` (codeatlas `7810b3b`, feature/semantic-retrieval)
on airflow at `7268d841` (PR #6222's head), with two stand-in keys: 9033 entities, criteria of both keys merged
with distinct ids, no header line in any criterion. The splitter keeps an issue's title inside the first criterion
when the text has no criteria list; labellers note such splits (guide 4.1).

**Trial draw (seed 20261114, to a temporary file):** 24 cases, 8 per repo. One shared key: AIRFLOW-3014 in
airflow #6241 and #6783 (AF-06, AF-07); the team decides whether they are one case group.

**Dev candidates outside the trial draw:** Airflow 195, Arrow 53, Spark 71 eligible (`dev_cases.py --candidates`).
The audit's examples pass the checks (airflow #6222, arrow #13191, spark #36006), but airflow #6222 is a revert
(`Revert "[AIRFLOW-5490] ..."`), so a different Airflow dev case is better. Choose after the official draw.

## Still open

- Team sign-off of the policy, quotas, case groups (AF-06/07) and guide v0.2; then the official draw.
- Choosing and freezing the three dev cases; building their packets.
- Label helpers (validate, agree, lock): not built; the label files are YAML and the dataset scripts use only the
  standard library.
- The frozen-case runner in CodeAtlas (`collect --frozen-case`): waits for Areej's agreement.
- Challenge scenarios for C4 and C8.
