# Challenge set: controlled scenarios

The real pilot (Airflow, Arrow, Spark) cannot show every situation the rules and the semantic gate must handle:
none of the windows has a CODEOWNERS file, Apache Jira has no approval workflow, and a PR whose criteria have no
matching code cannot be found from metadata. These scenarios are built on purpose, in a controlled repository and
Jira project, so each one tests exactly one situation.

**No-match is evaluated here, not on the real pilot.** `semantic_no_match` and `meaningful_link` are no longer
sampling categories (team decision B1, 20 Nov 2026): whether a criterion has matching code is an annotator's
judgement, not something the pool can know in advance. CH-11 covers it.

Each scenario gets a folder `eval/challenge/CH-NN/` frozen with `scripts/freeze_case.py` (set `challenge`).
Its `sources/` folder is never committed. The expected outcome is written from the baseline policy
(`eval/policies/baseline.yaml`) and `eval/LABELLING_GUIDE.md` before CodeAtlas is run on the scenario.

| ID | Scenario | Rule(s) | Expected outcome | Status |
|---|---|---|---|---|
| CH-01 | Code owner approved the head commit | C5 | to be written from the policy and guide | planned |
| CH-02 | Stale approval: owner approved an older commit, more commits pushed | C5 | to be written from the policy and guide | planned |
| CH-03 | Approval by a non-owner only | C5 | to be written from the policy and guide | planned |
| CH-04 | Owner is a team whose membership is inaccessible | C5 | to be written from the policy and guide | planned |
| CH-05 | No CODEOWNERS rule matches the changed files | C5 | to be written from the policy and guide | planned |
| CH-06 | Jira issue edited after the cutoff | C1, C6, semantic | to be written from the policy and guide | planned |
| CH-07 | Jira history cannot be reconstructed at the cutoff | C1, C3, C6 | to be written from the policy and guide | planned |
| CH-08 | PR changes a governance file | C2 | to be written from the policy and guide | planned |
| CH-09 | Policy file missing, or its hash does not match the case | all | to be written from the policy and guide | planned |
| CH-10 | Jira key absent, or ambiguous (several candidate keys) | C1, C3, C4, C6, C8, C9 | to be written from the policy and guide | planned |
| CH-11 | Criterion with no matching code (no-match) | semantic gate | to be written from the policy and guide | planned |
| CH-12 | Approval history inaccessible | C3, C5 | to be written from the policy and guide | planned |

Rules that cannot be estimated on the real pilot (`eval/rules_scope.yaml`) are tested here; the scenarios that
cover each are listed there.
