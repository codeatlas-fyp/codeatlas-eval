# Labelling guide

Version: v0 (outline, 11 Nov 2026). Becomes v1 when every rule section is written and agreed. Lock it before the
FYP-2 held-out set is opened. Each case records the version it was labelled under.

## 1. Scope

- A case is one real pull request (or one case group of related PRs).
- Decision cutoff: the PR's `merged_at` time in UTC. Nothing dated after it may be used.
- Allowed sources: the case's `sources/` folder and the GitHub and Jira web pages. Never CodeAtlas output, and never
  the other labeller's file.
- Anything you cannot see is recorded as inaccessible. "No access" is never "no approval".

## 2. Rules C1 to C9

Each section: when the rule applies; what supports SATISFIED; what supports VIOLATED and at which severity; when
evidence is insufficient; one positive and one negative worked example.

| Rule | Section owner | Status |
|---|---|---|
| C1 Requirement changed after work began | Areej | to write |
| C2 PR modifies its own governance | Yusra | to write |
| C3 Requirement not approved | Areej | to write (depends on the C3/C8 decision) |
| C4 Assignee is not the implementer | Saleha | to write |
| C5 Code owner did not approve the head commit | Yusra | to write |
| C6 Implementation built on a superseded version | Areej | to write |
| C7 Test evidence | Areej | to write |
| C8 Priority changed without authority | Areej | to write (depends on the C3/C8 decision) |
| C9 Unexplained code change | Yusra | to write |

## 3. Overall verdict

The fixed truth table, and how required rules with insufficient evidence give UNKNOWN.

## 4. Semantic matching (Yusra)

- What code behaviour supports a criterion.
- Eligible entities: non-test functions and methods under the analysis root at head.
- How to label related, unrelated and ambiguous candidates.
- No-match: search the whole candidate set (for example `git grep`), not only a tool's top five, and write why
  nothing qualifies.

## 5. Ownership

- Read CODEOWNERS at the base commit; the last matching line wins.
- Team owners whose membership at the cutoff is not visible are insufficient evidence.
- Approvals count only on the head commit.

## 6. Recording

- One-line reason per label, citing the source record.
- Minutes spent per case.
- How to mark a case indeterminate.

## 7. Version history

| Version | Date | Change | Agreed by |
|---|---|---|---|
| v0 | 11 Nov 2026 | Outline from the FYP-1 Final Build Plan, Appendix C-C | |
