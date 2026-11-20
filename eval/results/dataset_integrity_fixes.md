# Dataset integrity fixes and team decisions (branch `fix/dataset-integrity`)

Saleha, 20 Nov 2026. Built on Yusra's `feature/dataset-collection-yusra`. GitHub and Jira were read with GET
requests only. Nothing under `sources/`, `eval/pool/raw/` or `eval/repos/` is committed, and `eval/cases.csv` is
unchanged: the sampler was run only as a trial, outside the repository.

## What each fix does and how to run it

| Step | What it does | How to run it |
|---|---|---|
| A1 Historical Git pinning | `scripts/history.py` takes base, head and merge base from the merge commit (two parents: merge; one parent: the PR head from `pull/<n>/head`) and checks the diff against the PR file list: `historical_diff_status` is verified or unverifiable, with a reason. CODEOWNERS is read at `base_at_merge`. GitHub's refs are kept as `api_base_sha`/`api_head_sha` for comparison only. | `python scripts/update_pool.py --repo <repo> --history` |
| A2 Jira text at the cutoff | `jira_<KEY>_at_cutoff.txt` is rebuilt the way its source allows (archive: created text plus edits up to the cutoff; REST: later edits undone with `fromString`), with a header giving source, cutoff and reconstruction status. | runs inside `freeze_case.py` |
| A3 Atomic freeze | Each case is frozen into `<id>.staging/`, gets `manifest.json` (sha256 of every file, mandatory files, refs, `freeze_status`, tool version) and is then renamed with `os.replace`. A case is done only if its manifest checks out; an invalid or partial case is moved to `<id>.invalid-<UTC>` and frozen again. The annotators' files are never overwritten. | `python scripts/freeze_case.py --case ID`, `--all`, `--verify [--case ID]`, `--cases PATH`, `--out DIR` |
| A4 Reviews by the merge | Only APPROVED reviews submitted at or before the merge count in the pool. At freeze time, `reviews.json` holds reviews submitted by the cutoff and `reviews_post_cutoff.json` the later ones. | `python scripts/update_pool.py --repo <repo> --reviews` |
| A5 Jira link status | A key in a commit message, the branch or the merge commit (subject included) is verified. A key in the PR title is verified only if the timeline's `renamed` events show that title was in force at the merge. Anything else (e.g. description only) is uncertain. In the pool, `link_status` is verified / title_unchecked / uncertain, without network. | `python scripts/update_pool.py --repo <repo> --links`; full check in `freeze_case.py` |
| A6 Private data | `.gitignore` covers frozen sources, staging and invalid freezes. `scripts/pseudonymise.py` replaces e-mail addresses and GitHub logins with stable `user-NN` pseudonyms; the map stays in `../codeatlas-local/pseudonyms.yaml`. `scripts/audit_private.py` fails on tracked e-mail addresses, token-like strings, pseudonym maps or raw evidence. | `python scripts/pseudonymise.py FILE`; `python scripts/audit_private.py` before every push |
| B1 no_approval | The fallback category is `no_approval`, a sampling category, not a label; every `needs_manual` value in the pools (and the issue summaries derived from them) is renamed. No-match goes to the challenge set (`eval/challenge/README.md`, CH-01..CH-12, all planned). | in `build_pool.py` |
| B2 Rules not estimable | `eval/rules_scope.yaml`: C3, C4, C5, C8 are not estimable on the pilot, with the archive evidence; guide section "Rules not estimable on real data". | none |
| B3 Requirement quality | `requirement_quality` (unavailable / title_only / explicit_criteria / descriptive_issue) per key from the text at the cutoff; per pool row, the best among verified keys. Guide 4.0: title-only criteria are reported separately and criteria are never invented from a title. | `python scripts/update_pool.py --repo <repo> --quality` |
| B4 Every key kept | Every historically supported key is frozen with its own cutoff file, and `case.yaml` lists `jira_links`. The label templates have a per-key relevance block. Scored keys are verified AND adjudicated relevant (`eval/scoring_rules.md`, `scripts/scoring.py`). | inside `freeze_case.py` |
| B5 Baseline policy | `eval/policies/baseline.yaml`, in the CodeAtlas schema, with byte-identical copies per repo, marked DRAFT. `freeze_case.py` refuses to freeze without the repo's policy file and records `policy_sha256` and the status line. | see `eval/policies/README.md` |
| C Sampler | Quotas 7/6/7/2/2 (24, exactly 8 per repo; proposed, pending team approval). Allocation by deterministic backtracking, with the exact maximum from a max-flow and a shortfall table when infeasible. Inside a cell, a seeded choice with a preference order. The report records the seed and the pool sha256s. | `python scripts/sample_cases.py [--cases PATH --report PATH]` |

## Results on the pools of 20 Nov 2026

**A1 historical pinning (included rows).**

| Repo | Included | verified | unverifiable | Merge strategy |
|---|---|---|---|---|
| Airflow | 405 | 403 | 2 | all single_parent |
| Arrow | 75 | 75 | 0 | all single_parent |
| Spark | 125 | 125 | 0 | all single_parent |

The two unverifiable Airflow rows: #6272 (the commit on main also changes `.pre-commit-config.yaml`, which is not in
the PR's file list) and #6382 (the commit on main lacks `tests/gcp/hooks/test_dataflow.py`). No row has a CODEOWNERS
file at `base_at_merge`.

**A4 approvals by the merge.** Only Airflow #6420 and #6525 had an approval submitted after the merge; each still
had an earlier approval on the head commit, so `approvals_on_head` went from 2 to 1 and **no row changed category
in any repo**.

**A5 link status (included rows).** Airflow: 376 verified, 1 title_unchecked, 3 uncertain, 25 without a key.
Arrow: 72 verified, 3 without a key. Spark: 122 verified, 3 without a key. Earlier pools never read the subject of
the commit on main, where the merge scripts put the key; without it, 91 rows would have been title_unchecked.

**B1 no_approval (included rows).** Airflow 32, Arrow 8, Spark 5.

**B3 requirement quality (included keyed rows).** Airflow: 35 explicit_criteria, 211 descriptive_issue,
134 title_only. Arrow: 11, 57, 4. Spark: 11, 82, 29. No key is unavailable.

**C sampler trial run** (seed 20261114, written to a temporary folder, not to `eval/cases.csv`): 24 of 24
cases, 8 per repo, no shortfall.

| Repo | supported_approval | ownership_gap | no_approval | requirement_changed | no_key |
|---|---|---|---|---|---|
| Airflow | 3 | 2 | 3 | 0 | 0 |
| Arrow | 2 | 2 | 2 | 1 | 1 |
| Spark | 2 | 2 | 2 | 1 | 1 |

In the trial, Airflow #6241 and #6783 both carry AIRFLOW-3014: before the real draw, check whether they form one
case group (inclusion rule 6).

## Tests

Standard library `unittest`, no network; temporary Git repositories are built with the git CLI. Run with
`uv run --no-project python -m unittest discover -s tests -v`: 111 tests, all passing on 20 Nov 2026. New test
files: `test_freeze_atomic.py` (A3), `test_reviews_cutoff.py` (A4), `test_links.py` (A5), `test_private.py` (A6),
`test_categories.py` (B1), `test_rules_scope.py` (B2), `test_requirement_quality.py` (B3), `test_multi_key.py`
(B4), `test_policies.py` (B5) and `test_sampler.py` (C).

## Still open

- **Sign-off:** the baseline policy (Areej, Yusra, Saleha; `eval/policies/README.md`) and the quotas. Official
  labelling and the real draw wait for both.
- **Evaluation runner:** not built; `scripts/scoring.py` only defines which keys are scored.
- **Mail-archive completeness:** the archive is the only anonymous Jira source. The Arrow list holds only
  `[Created]` emails, so Arrow summary and description edits are invisible there. The text at the cutoff is then
  the created text and is still reported as `reconstructed`, so C1, C6 and `requirement_changed` can be missed for
  Arrow. The Arrow and Spark issues cached in `eval/pool/raw/` come from the REST API and have full histories, but
  they cannot be fetched again anonymously.
- **PR descriptions edited after the merge:** GitHub keeps no description history that the API returns, so a key
  found only in a description stays uncertain and is never scored.
- **Challenge set:** CH-01..CH-12 are planned, with expected outcomes still to be written. No scenario covers C4
  or C8 yet.
