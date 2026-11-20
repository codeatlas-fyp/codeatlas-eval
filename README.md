# CodeAtlas evaluation dataset (FYP-1)

Splits: `eval/cases/` = pilot (real public PRs), `eval/challenge/` = challenge (purposive real or constructed).
Rules and labelling: see `eval/LABELLING_GUIDE.md`. Sampling: see `eval/SAMPLING.md`. Data collection: see
`eval/results/dataset_collection_yusra.md`; integrity fixes and team decisions: `eval/results/dataset_integrity_fixes.md`.
Real identities are kept outside this repo: `scripts/pseudonymise.py` replaces e-mail addresses and GitHub logins with
pseudonyms (user-01, user-02, ...) and keeps the map in `../codeatlas-local/pseudonyms.yaml`. Raw evidence
(`sources/`, `eval/pool/raw/`, `eval/repos/`) is never committed; `scripts/audit_private.py` checks before a push.
Labels are human-written only. Labels are frozen (git tag) before any CodeAtlas run.
