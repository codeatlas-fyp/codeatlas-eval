# Scoring rules: which Jira keys count

Team decision B4 (20 Nov 2026). The same rule is coded in `scripts/scoring.py`, so scripts and tests share it.

## Every key is kept

A PR can name several Jira keys. Every key that the frozen history supports is kept: `freeze_case.py` freezes
each one (`jira_<KEY>.json`, `jira_<KEY>_at_cutoff.txt` with its source and reconstruction status) and lists it in
`case.yaml` under `jira_links` with `found_in`, `status` (verified | uncertain, see `scripts/links.py`),
`requirement_quality` and `reconstruction_status`, verified keys first, then by key. No key is ever dropped.

Annotators record a relevance for **every** key (`jira_links` in the label and adjudication files) before
labelling rules or criteria: `relevant`, `not_relevant` or `unclear`, with a one-line reason citing the source.

## Scored keys

A key is **scored** only if both hold:

1. its link status is `verified` (found in a commit message, the branch, the merge commit, or a PR title the
   timeline shows was in force at the merge), and
2. its adjudicated relevance is `relevant`.

| Link status | Adjudicated relevance | Treatment |
|---|---|---|
| verified | relevant | scored: governance rules and semantic criteria use it |
| verified | unclear | recorded, never scored |
| verified | not_relevant | recorded, never scored |
| uncertain | any | shown to annotators, never scored |

Semantic criteria are taken from every scored key and tagged with their key (`criterion_id` = `KEY:vN:acM`).

## A case with no scored key

The case is kept and stays in the coverage counts. The rules that need a requirement (C1, C3, C4, C6, C8, C9)
keep INSUFFICIENT_EVIDENCE; the other rules (C2, C5, C7) are scored as labelled. The case contributes no semantic
criteria.

## Rules not estimable on the pilot

Rules marked `estimable_on_real_data: false` in `eval/rules_scope.yaml` are excluded from the pilot metrics and
reported as "not estimable on this pilot"; see `eval/LABELLING_GUIDE.md`.
