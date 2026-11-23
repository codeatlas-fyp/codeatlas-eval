# Regression evidence for CA-12, CA-15 and CA-16

Requested by the supervisor's guide of 21 Nov 2026 (section 6) before any scored run. Run on 21 Nov 2026 on
`feature/dev-pilot-prep`. Full suite: 182 tests, OK.

| Issue | What the guide asks | Fix commits | Regression tests (all pass) | Real-data check |
|---|---|---|---|---|
| CA-12 historical content | A later Jira edit cannot leak into an earlier cutoff; current API fields kept apart from archive creation text; provenance and incomplete-history limits kept | 794da48 (text rebuilt by source), 18e9341 (REST cache preferred), 4f53db6 (created_text_only), 609c97d (unknown history never SATISFIED), 62e93a7 (per-key provenance), b6d3136 (reviews by the merge only), ac9658d (status, priority, assignee, resolution rebuilt at the cutoff) | 47 tests: test_jira_cutoff, test_jira_cache, test_created_text_only, test_jira_state, test_history_scoring, test_reviews_cutoff | `jira_state_check.md`: Arrow 77/77 and Spark 134/134 PR-key pairs rebuilt, changelogs complete and consistent; Airflow 416/416 correctly unavailable (mail archive) |
| CA-15 quota allocation | A feasible pool reaches 24 cases, 8 per repo, with the agreed categories; an infeasible pool reports a real shortfall; a seed alone does not solve coupled quotas | 4424f3e (allocation by backtracking with a shortfall table), 7faa4ad (case groups) | 6 tests: test_sampler (24 and 8 per repo, infeasible shortfall, backtracking fills what greedy could not, same seed same output) | Draw on the real pools, seed 20261114: 24 cases, 8 per repo, quotas 7/6/7/2/2 met, no shortfall |
| CA-16 freeze reliability | An interrupted case resumes safely; complete only after validation; pinned refs and cutoff; changed refs refused or frozen as a deliberate new version | 177ae34 (atomic freeze with manifest), 3dfccf6 (pinned base, head, merge base), db1531f (policy snapshot, stale labels), "fix(freeze): refuse a complete case whose row or policy changed" | 32 tests: test_freeze_atomic, test_freeze_audit, test_freeze_pinned, test_history | Content check on 603 verified pool PRs: 599 identical, 4 differ, all 4 inspected (`pilot_prep.md`) |

## The refusal added on 21 Nov

Before it, re-running the freeze on a complete case whose cases row had changed (commits, cutoff, PR number) or
whose policy file had changed printed "complete freeze verified, skipping" and kept the old evidence. It now
refuses, names every difference, changes nothing, and asks for `--refresh`, which keeps the old freeze aside and
marks carried labels stale.

## Not covered by these tests

- No real case has been frozen yet; the first freezes (dev case, then the draw) run on the machine with the
  GitHub token and the cache, and `freeze_case.py --verify` must report every case OK before labelling.
- The frozen-case runner in CodeAtlas does not exist yet; how it reads these files is fixed by
  `eval/FROZEN_CASE_CONTRACT.md`.
