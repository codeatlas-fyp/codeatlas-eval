# Policies

Team decision B5 (20 Nov 2026): **one baseline policy for every repository.**

- `baseline.yaml` is the policy. `airflow.yaml`, `arrow.yaml` and `spark.yaml` are byte-identical copies, because
  `freeze_case.py` reads `eval/policies/<repo>.yaml` and records its sha256 (`policy_sha256`) and status line in
  each `case.yaml`. A test checks that the three copies equal the baseline.
- **There are no repository-specific differences yet.** If one is ever needed, it is agreed by the three of us,
  written in the repo's file, and documented in the table "Repository-specific differences" below with its
  reason. Until then any difference between a repo file and `baseline.yaml` is a mistake.
- **Status: SIGNED OFF 23 Nov 2026** by Areej, Yusra and Saleha (table below). This is v1 for the current round;
  any later change is a new version and the cases are frozen again. Official labelling may start
  (`eval/LABELLING_GUIDE.md`). Once signed off, the first line of every file changes from `status: DRAFT ...` to
  `status: SIGNED OFF <date>`, which changes `policy_sha256`; cases frozen under the draft are frozen again.
- **DRAFT gate (audit 21 Nov):** `freeze_case.py` refuses to freeze a scored case (`set` pilot, held-out or
  challenge) while the repo's policy says DRAFT, and writes nothing. Dev cases (`set: dev`) freeze under the
  draft; `--allow-draft` overrides the gate for a trial freeze that will be redone.
- **Snapshot:** every frozen case keeps the exact policy bytes in `sources/effective_policy.yaml`, checksummed in
  the manifest; `freeze_case.py --verify` checks that its sha256 equals `policy_sha256`. A case can therefore be
  rerun with the policy it was frozen under even after this folder changes.

## How it was made

From `../codeatlas/config/policy.example.yaml`, in the CodeAtlas `Policy` schema (`src/codeatlas/schema/policy.py`:
unknown fields are an error). No field was added; the file validates with `Policy.model_validate`. Reviewed
against the rules in `src/codeatlas/evaluate/rules/`:

| Setting | Example | Baseline | Why |
|---|---|---|---|
| `workitem_key_pattern` | `[A-Z]+-\d+` | `\b(?:AIRFLOW\|ARROW\|SPARK)-\d+\b` | **Changed.** The generic pattern also matches `UTF-8`, `SHA-256` or `ISO-8601` in PR titles and commit messages, which would invent work items. The three project keys, in one pattern, keep the file identical across repos. |
| `requirement_fields` | summary, description, acceptance_criteria | same | Kept. Apache Jira has no acceptance-criteria field; an absent field is simply empty. |
| `governance_paths` | CODEOWNERS (3 locations), `docs/adr/**`, `.codeatlas/**`, `.github/workflows/**`, `.pre-commit-config.yaml` | same, plus `.asf.yaml` | **Added `.asf.yaml`.** In Apache repositories it sets branch protection, required reviews and merge options, so a PR that edits it changes its own governance (C2). The other paths are kept: CODEOWNERS and workflows govern review and CI; `docs/adr/**` and `.codeatlas/**` do not exist in these repos and cost nothing. |
| `approval` | status `Approved`, `approver_account_ids: [user-01]` | same | Kept. The schema needs a group or an account id. Apache Jira workflows have no approval status, so C3 is not estimable on the pilot (`eval/rules_scope.yaml`); the placeholder is a pseudonym, not a real account. |
| `priority_authority` | `account_ids: [user-01]` | same | Kept, same reason (C8 not estimable on the pilot). |
| `cases.C3.severity` | block | block | Kept. Matches the C3 rule's own default. |
| `cases.C5.severity` | block | block | Kept. Matches the C5 rule's default and the spec (no CODEOWNERS on the pilot, so it matters on the challenge set). |
| `cases.C7.required_when_label` | `requires-test-evidence` | same | Kept. Apache issues do not use this label, so the C7 stub is NOT_APPLICABLE on every pilot case. |
| other rules | not set | not set | Kept at the rules' defaults: C1, C2, C4, C6, C8 review; C9 review (advisory; the schema forbids block). |
| `semantic.top_k` | 5 | 5 | Kept. Scoring uses the full ranking anyway (guide 4.5). |

## Repository-specific differences

| Repository | Setting | Difference | Reason | Agreed on |
|---|---|---|---|---|
| (none) | | | | |

## Sign-off

| Name | Date |
|---|---|
| Areej | 23 Nov 2026 |
| Yusra | 23 Nov 2026 |
| Saleha | 23 Nov 2026 |
