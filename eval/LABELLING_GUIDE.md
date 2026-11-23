# Labelling guide

Version: v0.1 (outline 11 Nov 2026; Yusra's sections drafted 17 Nov 2026). Becomes v1 when every rule section is written and agreed. Lock it before the
FYP-2 held-out set is opened. Each case records the version it was labelled under.

## 1. Scope

- A case is one real pull request (or one case group of related PRs).
- Decision cutoff: the PR's `merged_at` time in UTC. Nothing dated after it may be used.
- Allowed sources: the case's `sources/` folder and the GitHub and Jira web pages. Never CodeAtlas output, and never
  the other labeller's file.
- Anything you cannot see is recorded as inaccessible. "No access" is never "no approval".
- Policy: every case uses the baseline policy (`eval/policies/`, identical for all repos), recorded in
  `case.yaml` as `policy_sha256` and `policy_status`. **Official labelling must not start while the policy status
  is DRAFT**: practice labels made under a DRAFT policy are not used in the metrics.

## 2. Rules C1 to C9

Each section: when the rule applies; what supports SATISFIED; what supports VIOLATED and at which severity; when
evidence is insufficient; one positive and one negative worked example.

| Rule | Section owner | Status |
|---|---|---|
| C1 Requirement changed after work began | Areej | to write |
| C2 PR modifies its own governance | Yusra | draft below |
| C3 Requirement not approved | Areej | to write (depends on the C3/C8 decision) |
| C4 Assignee is not the implementer | Saleha | to write |
| C5 Code owner did not approve the head commit | Yusra | draft below |
| C6 Implementation built on a superseded version | Areej | to write |
| C7 Test evidence | Areej | to write |
| C8 Priority changed without authority | Areej | to write (depends on the C3/C8 decision) |
| C9 Unexplained code change | Yusra | draft below |

### Rules not estimable on real data

`eval/rules_scope.yaml` lists, for each rule, whether the real pilot can estimate it and why. On this pilot
**C3, C4, C5 and C8 are not estimable**: no window has a CODEOWNERS file (C5), and the mail archive, the only
anonymous Jira source, carries no status or priority history and no complete assignee history (C3, C4, C8).

- Annotators still label these rules on every case: NOT_APPLICABLE or INSUFFICIENT_EVIDENCE, with the usual
  one-line reason (for example "no CODEOWNERS file at base" or "archive has no status history").
- Metrics exclude them and report them as "not estimable on this pilot", never as agreement or accuracy.
- They are tested on the challenge set instead (`eval/challenge/README.md`; `tested_instead` in the scope file).

### C2 PR modifies its own governance (Yusra, draft)

**Applies:** always. Every PR either touches governance files or it does not, so C2 is never
NOT_APPLICABLE.

**Governance files** are the paths listed under `governance_paths` in the case's policy file,
matched against the PR's changed files. The default list: `CODEOWNERS`, `.github/CODEOWNERS`,
`docs/CODEOWNERS`, `docs/adr/**`, `.codeatlas/**`, `.github/workflows/**`,
`.pre-commit-config.yaml`. Use the case's own policy file, not this list, if they differ.

- **VIOLATED (review):** at least one file in `sources/files.json` matches a governance path.
  Reason names the file(s). A rename *into or out of* a governance path counts.
- **SATISFIED:** no changed file matches any governance path.
- **INSUFFICIENT_EVIDENCE:** only if the PR's file list could not be fetched (recorded as
  inaccessible). Never because a file "looks
  harmless": a one-character CODEOWNERS edit still violates.

**Worked examples.** VIOLATED: the PR edits `.github/workflows/ci.yml` alongside code, reason
"changes .github/workflows/ci.yml (governance path)". SATISFIED: the PR changes only
`airflow/models/dag.py` and `tests/models/test_dag.py`.

### C5 Code owner did not approve the head commit (Yusra, draft)

Work from `sources/CODEOWNERS_at_base.txt`, `sources/files.json`, `sources/reviews.json` and
`sources/commits.json`. Ownership is read at the **base** commit; approval must be on the
**head** commit.

1. **Find the owners of each changed file.** In CODEOWNERS the **last** matching line wins.
   Use the file GitHub itself uses at base, in this order: `.github/CODEOWNERS`, then root
   `CODEOWNERS`, then `docs/CODEOWNERS` (the first that exists; CA-03).
2. **Find valid approvals.** A review counts only if its state is `APPROVED` **and** its
   `commit_id` equals the head SHA. An approval on an earlier commit followed by more pushes
   is stale and does not count. A comment or "LGTM" without the APPROVED state does not count.
3. **Decide per file, then for the case** (the case takes the worst file result):

| Situation for a file | Label |
|---|---|
| An owner (a person, or a member of an owner team whose membership you can see at the cutoff) approved the head commit, and is not the PR author | SATISFIED |
| Owners are resolvable people and none approved the head commit | VIOLATED (block) |
| The owner is a team whose membership at the cutoff is not visible, an email address, or only the PR author | INSUFFICIENT_EVIDENCE |
| No CODEOWNERS file at base, or no line matches the file | NOT_APPLICABLE for that file |

**Missing ownership evidence is never SATISFIED** (CA-01): "nobody objected" or "an
approver who is probably an owner" is INSUFFICIENT_EVIDENCE, with the gap written down.
If every file is NOT_APPLICABLE the case is NOT_APPLICABLE.

**Worked examples.** VIOLATED: `@alice` owns `libcloud/compute/*`, `@bob` approved the head
commit but owns nothing touched, `@alice` approved an older commit only. INSUFFICIENT_EVIDENCE:
the only owner is `@apache/airflow-committers` and the team's membership at the cutoff is not
visible; reason "owner is a team; membership at cutoff inaccessible".

### C9 Unexplained code change (Yusra, draft)

C9 is **advisory**: it never blocks a verdict by itself. It asks whether each changed,
non-test function or method is explained by the work item.

**Applies** to changed functions and methods outside test files (`tests/`, `test_*.py`,
`*_test.py`, `conftest.py`). If the PR changes no such entity, NOT_APPLICABLE.

For each such entity, it is **explained** when both hold:
1. at least one commit that touched it carries a Jira key in its message, and
2. it implements, directly or as a necessary part, at least one acceptance criterion of a
   linked issue, as you labelled it in Section 4 (it is in that criterion's `relevant` list).

- **VIOLATED (review):** at least one changed entity is unexplained. Reason names up to three
  entities and why (for example "commit has no key" or "not relevant to any criterion of
  AIRFLOW-1234").
- **SATISFIED:** every changed non-test entity is explained.
- **INSUFFICIENT_EVIDENCE:** the linked issue has no usable text (no description and no
  acceptance criteria), so relevance cannot be judged.

Mechanical edits made necessary by the change (renaming a call site, adjusting an import,
updating a type hint) count as explained if the entity they serve is relevant; write
"follows from <entity>" in the reason.

## PRs with several Jira keys

Every key the history supports is frozen and listed in `case.yaml` under `jira_links` (verified keys first). No
key is dropped, and you decide relevance, not the scripts (`eval/scoring_rules.md`).

1. **Before labelling any rule or criterion**, fill `jira_links` in your label file with one entry for **every**
   key in `case.yaml`: `relevance` is `relevant`, `not_relevant` or `unclear`, and `reason` is one line citing the
   source (commit, title, issue text).
2. **Relevant:** the PR does the work the issue asks for, or a necessary part of it.
   Example (illustrative): commit "[AIRFLOW-5477] Rewrite PubSub hook" and AIRFLOW-5477 is "Rewrite Google PubSub Hook to Google
   Cloud Python": relevant, reason "commit implements the issue's hook rewrite".
3. **Not relevant:** the key is mentioned but the PR does not do its work: "see also AIRFLOW-1234", a follow-up
   ("AIRFLOW-1300 will handle the docs"), the issue that introduced the bug being fixed, or a duplicate.
   Example: description says "follow-up to AIRFLOW-5400": not_relevant, reason "PR body: named as the earlier
   change, not implemented here".
4. **Unclear:** you cannot decide from the sources. Write `unclear` with what is missing (for example "issue text
   is title only; PR changes a different module"). Do not force a choice; the adjudicator resolves it, and a key
   that stays unclear is recorded but never scored.
5. **Scored keys** are those with `status: verified` **and** adjudicated relevance `relevant`. Uncertain keys
   (for example only in the PR description) are shown to you but never scored, whatever you label.
6. Rules that need a requirement use only scored keys. If a case has no scored key, those rules (C1, C3, C4, C6,
   C8, C9) stay INSUFFICIENT_EVIDENCE and the case still counts for coverage.
7. **Criteria** are taken from every scored key and each is tagged with its key (`criterion_id` starts with the
   key, e.g. `AIRFLOW-5477:v1:ac1`).

## 3. Overall verdict

The fixed truth table, and how required rules with insufficient evidence give UNKNOWN.

## 4. Semantic matching (Yusra, draft)

This section defines the **semantic labels**: for each acceptance criterion, which code
implements it. They are the ground truth for the semantic evaluation, so they are written
blind: never look at CodeAtlas candidates, scores or rankings before the labels are frozen.

### 4.0 Which criteria get semantic labels (requirement quality)

Each Jira key has a `requirement_quality` (pool column; `jira_links` in `case.yaml`), from the issue text at the
cutoff: `explicit_criteria` (a numbered or bulleted list, or the words "acceptance criteria"), `descriptive_issue`
(a description without a list), `title_only` (no description) or `unavailable` (issue not found).

- **Semantic relevance labels are given only for criteria from `explicit_criteria` or `descriptive_issue`
  issues.** These are the criteria the semantic metrics are computed on.
- **`title_only` criteria are labelled and reported separately.** Label them the same way, but they are never
  pooled with the others: the report shows their results in a separate row.
- **Never invent criteria from a title.** A title is one criterion as written; do not expand it into the steps
  you think it implies, and do not borrow text from the PR description or the code.
- `unavailable` issues have no criteria; record the gap and move on.

### 4.1 What you work from

`scripts/prepare_packets.py` (dataset repo) builds `<case>/packet/` with CodeAtlas's `scripts/prepare_case.py`
(branch `feature/semantic-retrieval`): one run per scored key on the issue text at the cutoff (the metadata header
of `jira_<KEY>_at_cutoff.txt` is stripped), the criteria of all keys merged into one file, one entity list.
`packet/PACKET.json` records the head SHA, analysis root, keys used and skipped, and the tool's sha256 and commit.
The packet has:

- `criteria.csv`: the issue's acceptance criteria split exactly as CodeAtlas splits them,
  each with a `criterion_id` (`KEY:vN:acM`). Label every row. Never rewrite or merge the text;
  if the split is wrong (two requirements in one row, a heading as a row), label it as it is
  and say so in `note`.
- `entities.csv`: **every** function, method and class at the head commit under the analysis
  root, with its `label_ref` (`path.py::Class.method`). It is an alphabetical list, not a
  ranking, and contains no scores.

Search the code yourself: the GitHub file view at the head SHA, `git grep -n "<word>" <head_sha>`
in the clone, and the PR diff. Never use a tool's "top results".

### 4.2 What counts as relevant

An entity is **relevant** to a criterion when its body carries out the behaviour the criterion
asks for, or a necessary step of it (validation the criterion requires, the computation it
names, the call that makes it happen). Write entities as `label_ref` values from
`entities.csv`, copied exactly.

- **Relevant:** the method that computes the late fee for "charge a late fee per overdue day".
- **Related, not relevant:** code that is nearby or similar but does not do it (a logger, a
  generic helper, the caller that only passes values through). Put these under `related` if
  you want to record them; they are not scored as correct.
- **Tests are never relevant.** A test that checks the behaviour is evidence for C7, not an
  implementation.
- A class is relevant only when the criterion is about the class as a whole (for example
  "add a new operator"); otherwise name the method.
- Changed or unchanged does not matter. The relevant code may already exist before the PR;
  label it anyway.
- **Deleted code is not a candidate.** `entities.csv` is the code at the head commit, so an entity the PR removed
  is not in it. If a criterion was met only by deleting code, write no match with the rationale "met by deletion
  of <path>::<name>" and the adjudicator counts it separately.

### 4.3 No match

A criterion is **no match** when no entity at the head commit implements it (for example the
criterion is about documentation, configuration, UI text or a process, or the work is in
another language or outside the analysis root). Before writing no match:

1. search the **whole** entity list and the repository with at least two key words and their
   synonyms (`git grep -n -i`), not only the changed files;
2. write `no_match_rationale`: the searches you ran and why nothing qualifies.

A criterion with relevant entities never also gets no match.

### 4.4 Ambiguity and confidence

If you are unsure, still give your best label and set `confidence: unsure` with a one-line
reason. The adjudicator resolves disagreements against this section; if this section cannot
settle it, the criterion is marked indeterminate and excluded from the metrics (and counted).

### 4.5 How the labels are scored (so labellers know what matters)

Scoring uses each ranker's **full ranking** of all entities, not a fixed top 5: the rank of the
first relevant entity (median rank, MRR, recall at 1, 5, 10, 20 and 50). No-match criteria are
scored by whether the gate abstained. So it matters that `relevant` is complete (every entity
that implements the criterion) and that no-match is only used after a whole-repository search.

## 5. Ownership

- Read CODEOWNERS at the base commit; the last matching line wins.
- Team owners whose membership at the cutoff is not visible are insufficient evidence.
- Approvals count only on the head commit.

## 6. Recording

- Label only cases without `LABELS_STALE.txt`; if a case has one, its evidence or policy changed after you labelled
  it: relabel from the new sources, then remove the file.
- Dev cases (`AF-D01`, `AR-D01`, `SP-D01`) are for practice and debugging; their labels are never scored.

- One-line reason per label, citing the source record.
- Minutes spent per case.
- How to mark a case indeterminate.

## 7. Version history

| Version | Date | Change | Agreed by |
|---|---|---|---|
| v0 | 11 Nov 2026 | Outline from the FYP-1 Final Build Plan, Appendix C-C | |
| v0.1 | 17 Nov 2026 | Drafts of C2, C5, C9 and Section 4 (semantic matching) | (to agree) |
| v0.2 | 21 Nov 2026 | Packets from prepare_packets.py, deleted code, stale labels, dev cases | (to agree) |
