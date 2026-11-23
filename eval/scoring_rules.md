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

## Keys whose edit history is unknown (created_text_only)

The issue text at the cutoff comes from a cached REST copy when one exists in `eval/pool/raw/` (source
`jira_rest_cache`, later edits undone with their old values), otherwise from the mail archive. When the archive
holds only the issue's Created email (Arrow's list), the created text is known but not whether it was edited:
`reconstruction_status` is `created_text_only` ("edit history not available in the archive").

- **C1 and C6** for a scored key with `created_text_only` are **INSUFFICIENT_EVIDENCE (history unknown), never
  SATISFIED**. A VIOLATED label stands only if another scored key, whose history is known, carries it.
- These keys and their cases are **reported separately** (`history_unknown_keys` in `scripts/scoring.py`), never
  pooled with the keys whose history is known.
- **Sampling:** a pool row with such a key cannot be proven unchanged. `build_pool.requirement_edited` gives
  "unknown", not "unchanged", and the sampling report lists such sampled rows in their own table. They are
  never counted as evidence that a requirement stayed the same.

## Cases that are not scored (audit 21 Nov)

- **Historical diff:** a scored case needs `historical_diff_status: verified` (the files changed between
  `merge_base_sha` and `head_at_merge` are the PR's file list). An `unverifiable` case is kept and reported but
  not scored.
- **Historical content:** `historical_content_status` compares, file by file, the change the PR made with the
  change that landed on the main branch (`git patch-id --stable`). `identical` is the normal case. `differs`
  means the merge script, a conflict resolution or an evil merge changed what landed: an adjudicator inspects the
  case before it is scored and records the decision in `case.yaml` `notes`. `not_checked` means the file list was
  not verified, so the case is already unscored.
- **Stale labels:** labels in a case folder with `LABELS_STALE.txt` were made on other evidence or another policy
  (`freeze_case.py --refresh`). They do not count until the case is relabelled and the file is removed.
- **Dev cases** (`set: dev`, `eval/dev_cases/`) are never scored and never pooled with the 24.

## Rules not estimable on the pilot

Rules marked `estimable_on_real_data: false` in `eval/rules_scope.yaml` are excluded from the pilot metrics and
reported as "not estimable on this pilot"; see `eval/LABELLING_GUIDE.md`.
