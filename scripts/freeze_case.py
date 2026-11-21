"""Freeze the evidence for sampled cases (build plan C5 step 3), atomically and with a manifest.

Usage:
    python scripts/freeze_case.py --case AF-01
    python scripts/freeze_case.py --all
    python scripts/freeze_case.py --verify                 # check every frozen case: OK / INVALID with reasons
    python scripts/freeze_case.py --verify --case AF-01
    python scripts/freeze_case.py --all --cases %TEMP%\\cases.csv --out %TEMP%\\frozen   # test outside the repo

For each case the evidence is written into <out>/<id>.staging/: case.yaml, sources/ (PR, commits, files, reviews.json
with the reviews submitted at or before the cutoff and reviews_post_cutoff.json with the later ones,
timeline.json, jira_links.json with where each key was found and its link status (A5: verified from a commit, the
branch, the merge commit, or a title the timeline shows was in force at the merge; otherwise uncertain),
Jira issues with changelog, jira_<KEY>_at_cutoff.txt with the issue text at the cutoff, CODEOWNERS_at_base.txt read
at base_at_merge, history.json with the pinned refs, fetched_at.txt), checklist.csv and the label files. When
everything is written, manifest.json is written last (sha256 of every frozen file, the mandatory-file list, the
refs, freeze_status "complete", the tool version) and the folder is renamed to <out>/<id>/ with os.replace.
An interrupted freeze therefore never leaves a final folder.

A case counts as frozen only if its manifest exists and every checksum and mandatory file checks out; a
non-empty sources/ folder is not enough. An invalid or partial case is moved to <id>.invalid-<UTC timestamp>/
(with REASON.txt) and frozen again. The annotators' files (label_A.yaml, label_B.yaml, adjudicated.yaml,
checklist.csv) are never overwritten: they are carried over into the new freeze, and they are not checksummed
because people edit them. Nothing is written to GitHub or Jira.

Audit of 21 Nov 2026:
- The policy's exact bytes are frozen as sources/effective_policy.yaml (checksummed; --verify checks that its
  sha256 equals policy_sha256), so an old case can be rerun with the policy it was frozen under.
- A DRAFT policy freezes only a dev case (set "dev") or with --allow-draft (an engineering freeze that is repeated
  after sign-off). Scored cases need the signed-off policy.
- When a refreeze carries filled-in labels over and the evidence or the policy changed, LABELS_STALE.txt lists
  what changed: those labels must be reviewed and relabelled before they count (--verify reports it). Blank
  templates are never stale.
- Dev cases (eval/dev_cases.csv, set "dev") freeze into eval/dev_cases/ by default.
- packet/ (criteria.csv, entities.csv written by scripts/prepare_packets.py) and run/ are outside the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (EVAL, codeowners_at, dump_json, ensure_clone, find_keys, gh, git, jira_issue_for, merged_branch_messages,
                    read_csv, repo_cfg, write_csv)
from case_groups import group_of, load_groups
from history import pin
from jira_archive import cutoff_file_text, reconstruct_at, state_at, state_summary
from links import VERIFIED, freeze_link_statuses, title_at
from requirement_quality import UNAVAILABLE, classify_issue

TEMPLATES = EVAL / "templates"
POLICIES = EVAL / "policies"
FREEZE_TOOL_VERSION = "freeze_case.py 4"
MANIFEST = "manifest.json"
# edited by people after the freeze: never overwritten, never checksummed
ANNOTATOR_FILES = ("checklist.csv", "label_A.yaml", "label_B.yaml", "adjudicated.yaml")
STALE = "LABELS_STALE.txt"   # written by a refreeze that changed labelled evidence; removed by people after relabelling
UNCHECKED_DIRS = ("run/", "packet/")
POLICY_SNAPSHOT = "sources/effective_policy.yaml"
MANDATORY = ["case.yaml", "sources/pr.json", "sources/commits.json", "sources/reviews.json",
             "sources/reviews_post_cutoff.json", "sources/files.json", "sources/history.json", "sources/CODEOWNERS_at_base.txt", "sources/fetched_at.txt",
             POLICY_SNAPSHOT]


# ---------------------------------------------------------------- manifest and verification


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def frozen_files(case_dir: Path) -> list[str]:
    """Every file the manifest covers (posix paths): all but the manifest, the annotator files, LABELS_STALE.txt,
    run/ and packet/."""
    out = []
    for p in sorted(case_dir.rglob("*")):
        rel = p.relative_to(case_dir).as_posix()
        if (p.is_file() and rel not in (MANIFEST, STALE) and rel not in ANNOTATOR_FILES
                and not rel.startswith(UNCHECKED_DIRS)):
            out.append(rel)
    return out


def write_manifest(case_dir: Path, mandatory: list[str], refs: dict[str, str]) -> None:
    manifest = {
        "freeze_status": "complete",
        "freeze_tool_version": FREEZE_TOOL_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mandatory_files": sorted(mandatory),
        "refs": refs,
        "files": {rel: sha256_file(case_dir / rel) for rel in frozen_files(case_dir)},
    }
    dump_json(case_dir / MANIFEST, manifest)


def verify_case(case_dir: Path) -> list[str]:
    """Reasons the case is not a complete freeze; an empty list means OK."""
    if not case_dir.is_dir():
        return ["case folder missing"]
    mpath = case_dir / MANIFEST
    if not mpath.exists():
        return ["no manifest.json (freeze never completed)"]
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"manifest.json unreadable: {e}"]
    reasons = []
    if manifest.get("freeze_status") != "complete":
        reasons.append(f"freeze_status is {manifest.get('freeze_status')!r}, not 'complete'")
    listed = manifest.get("files", {})
    for rel in manifest.get("mandatory_files", []):
        if rel not in listed or not (case_dir / rel).is_file():
            reasons.append(f"mandatory file missing: {rel}")
    for rel, digest in sorted(listed.items()):
        p = case_dir / rel
        if not p.is_file():
            reasons.append(f"file missing: {rel}")
        elif sha256_file(p) != digest:
            reasons.append(f"checksum mismatch: {rel}")
    for rel in frozen_files(case_dir):
        if rel not in listed:
            reasons.append(f"file not in manifest: {rel}")
    for name in ANNOTATOR_FILES:
        if not (case_dir / name).is_file():
            reasons.append(f"annotator file missing: {name}")
    want = manifest.get("refs", {}).get("policy_sha256")
    snap = case_dir / POLICY_SNAPSHOT
    if want and snap.is_file() and sha256_file(snap) != want:
        reasons.append(f"{POLICY_SNAPSHOT} does not match policy_sha256 in the manifest refs")
    return reasons


def stale_note(case_dir: Path) -> str | None:
    """The LABELS_STALE.txt text if the case's labels must be reviewed and relabelled, else None."""
    p = case_dir / STALE
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def _replace_dir(src: Path, dest: Path) -> None:
    """os.replace a folder; OneDrive sometimes answers 'Access is denied' for a moment, so retry once."""
    try:
        os.replace(src, dest)
    except PermissionError:
        time.sleep(5)
        os.replace(src, dest)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- evidence


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def split_reviews(reviews: list[dict[str, Any]], cutoff: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(submitted at or before the cutoff, the rest). A review with no submitted_at (pending) was not given by then."""
    before, after = [], []
    for r in reviews:
        at = r.get("submitted_at")
        (before if at and _utc(at) <= _utc(cutoff) else after).append(r)
    return before, after


LINK_FIELDS = ("key", "found_in", "status", "requirement_quality", "reconstruction_status", "state_at_cutoff",
               "source")


def sort_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verified keys first, then by key."""
    return sorted(links, key=lambda x: (x["status"] != VERIFIED, x["key"]))


def jira_links_yaml(links: list[dict[str, Any]]) -> str:
    """The jira_links value for case.yaml: one flow mapping per key, or [] when the case has no key."""
    if not links:
        return " []"
    lines = []
    for x in links:
        parts = [f"key: {x['key']}", f"found_in: [{', '.join(x['found_in'])}]"]
        parts += [f"{f}: {x[f]}" for f in LINK_FIELDS[2:]]
        lines.append("  - {" + ", ".join(parts) + "}")
    return "\n" + "\n".join(lines)


def key_sources(repo: Path, cfg: dict[str, Any], pr: dict[str, Any], commits: list[dict[str, Any]],
                merge_sha: str) -> dict[str, set[str]]:
    """{key: locations}: title, branch, body, commit (PR commits) and merge_commit (the commit on main and,
    for a true merge, the messages it brought in)."""
    merge_text = git(repo, "log", "-1", "--format=%B", merge_sha, check=False)
    ps = git(repo, "rev-list", "--parents", "-n", "1", merge_sha, check=False).split()[1:]
    merge_text += merged_branch_messages(repo, {"parents": ps})
    texts = {"title": pr.get("title", ""), "branch": (pr.get("head") or {}).get("ref", ""), "body": pr.get("body") or "",
             "commit": "\n".join(c["commit"]["message"] for c in commits), "merge_commit": merge_text}
    where: dict[str, set[str]] = {}
    for loc, text in texts.items():
        for k in find_keys(text, cfg["key_regex"]):
            where.setdefault(k, set()).add(loc)
    return where


def is_draft(status_line: str) -> bool:
    return "DRAFT" in status_line.upper()


def check_policy_gate(row: dict[str, str], allow_draft: bool) -> None:
    """A DRAFT policy freezes a dev case, or any case with --allow-draft (an engineering freeze); nothing else."""
    _, _, status = policy_for(row["repo"])
    if is_draft(status) and row.get("set") != "dev" and not allow_draft:
        raise SystemExit(f"{row['case_id']}: eval/policies/{row['repo']}.yaml is still DRAFT ({status!r}). Scored cases "
                         f"are frozen under the signed-off policy (eval/policies/README.md). For an engineering "
                         f"freeze that will be repeated after sign-off, add --allow-draft. Nothing written.")


def policy_for(repo: str) -> tuple[Path, str, str]:
    """(path, sha256, status line) of eval/policies/<repo>.yaml. Exits with a clear error if it is missing."""
    path = POLICIES / f"{repo}.yaml"
    if not path.is_file():
        raise SystemExit(f"policy file {path} is missing: refusing to freeze (nothing written). "
                         f"Copy eval/policies/baseline.yaml to it (eval/policies/README.md).")
    first = path.read_text(encoding="utf-8").splitlines()[:1]
    return path, sha256_file(path), (first[0].lstrip("# ").strip() if first else "")


def merge_commit_for(row: dict[str, str]) -> str:
    """The PR's commit on the main branch: from the cases row if it has one, else from the repo's pool.

    GitHub's own merge_commit_sha is not used: for script-merged PRs (Arrow, Spark) it is a test merge that
    never reached the main branch.
    """
    if row.get("merge_commit_sha"):
        return row["merge_commit_sha"]
    for r in read_csv(EVAL / "pool" / f"{row['repo']}_pool.csv"):
        if r["pr_number"] == str(row["pr_number"]) and r.get("merge_commit_sha"):
            return r["merge_commit_sha"]
    raise SystemExit(f"{row['case_id']}: no merge_commit_sha for #{row['pr_number']} in the case row or the pool")


def collect(row: dict[str, str], case_dir: Path) -> dict[str, Any]:
    """Fetch and write the evidence of one case into case_dir. Returns the extra mandatory files and the refs."""
    cid = row["case_id"]
    cfg = repo_cfg(row["repo"])
    src = case_dir / "sources"
    repo = ensure_clone(cfg)
    n = row["pr_number"]
    pr = gh(f"repos/{cfg['github']}/pulls/{n}")
    data = {"pr": pr,
            "commits": gh(f"repos/{cfg['github']}/pulls/{n}/commits", paginate=True),
            "reviews": gh(f"repos/{cfg['github']}/pulls/{n}/reviews", paginate=True),
            "files": gh(f"repos/{cfg['github']}/pulls/{n}/files", paginate=True)}
    cutoff = pr.get("merged_at") or row["decision_cutoff_utc"]  # script-merged PRs: the pool's merge time
    # reviews.json holds only what was submitted by the cutoff; later reviews are kept apart, never used
    data["reviews"], data["reviews_post_cutoff"] = split_reviews(data["reviews"], cutoff)
    for name, d in data.items():
        dump_json(src / f"{name}.json", d)
    mandatory = []

    # A5: where each key was found and whether that ties it to the PR at the merge
    merge_sha = merge_commit_for(row)
    try:
        timeline = gh(f"repos/{cfg['github']}/issues/{n}/timeline", paginate=True)
        dump_json(src / "timeline.json", timeline)
        mandatory.append("sources/timeline.json")
        merged_title: str | None = title_at(pr.get("title", ""), timeline, cutoff)
    except Exception as e:  # noqa: BLE001 - recorded; title keys then stay uncertain
        (src / "timeline.INACCESSIBLE.txt").write_text(f"{e}\n", encoding="utf-8")
        mandatory.append("sources/timeline.INACCESSIBLE.txt")
        merged_title = None
    links = freeze_link_statuses(key_sources(repo, cfg, pr, data["commits"], merge_sha), merged_title, cfg["key_regex"])
    dump_json(src / "jira_links.json", {"title_at_merge": merged_title, "links": links})
    mandatory.append("sources/jira_links.json")
    # B4: every historically supported key is frozen (verified and uncertain alike); none is dropped
    keys = sorted({k for k in row["jira_keys"].split(";") if k} | {x["key"] for x in links})
    by_key = {x["key"]: x for x in links}
    jira_links = []
    for k in keys:
        link = by_key.get(k) or {"key": k, "found_in": ["case_row"], "status": "uncertain",
                                 "reason": "listed in the case row but not found in the PR, its commits or the merge"}
        entry = {"key": k, "found_in": link["found_in"], "status": link["status"]}
        try:
            issue = jira_issue_for(cfg, k, n)   # cached REST copy first, else Jira or the archive
        except Exception as e:  # noqa: BLE001
            (src / f"jira_{k}.INACCESSIBLE.txt").write_text(f"{e}\n", encoding="utf-8")
            (src / f"jira_{k}_at_cutoff.txt").write_text(
                f"key: {k}\nsource: none\ncutoff: {cutoff}\nreconstruction_status: inaccessible\n"
                f"reconstruction_note: {type(e).__name__}\n---\n", encoding="utf-8")
            dump_json(src / f"jira_{k}_state_at_cutoff.json", state_at({"key": k, "source": "none"}, cutoff))
            mandatory += [f"sources/jira_{k}.INACCESSIBLE.txt", f"sources/jira_{k}_at_cutoff.txt",
                          f"sources/jira_{k}_state_at_cutoff.json"]
            jira_links.append(entry | {"requirement_quality": UNAVAILABLE, "source": "none",
                                       "reconstruction_status": "inaccessible", "state_at_cutoff": "unavailable"})
            continue
        dump_json(src / f"jira_{k}.json", issue)
        # the issue as it stood at the decision cutoff, rebuilt the way its source allows: a header (source,
        # cutoff, reconstruction status), '---', then the text (none if unverifiable)
        (src / f"jira_{k}_at_cutoff.txt").write_text(cutoff_file_text(issue, cutoff), encoding="utf-8")
        # status, priority, assignee, resolution at the cutoff: rebuilt from the changelog, or marked missing;
        # the fields of jira_<KEY>.json are the state when fetched and are never used as the state at the cutoff
        state = state_at(issue, cutoff)
        dump_json(src / f"jira_{k}_state_at_cutoff.json", state)
        mandatory += [f"sources/jira_{k}.json", f"sources/jira_{k}_at_cutoff.txt",
                      f"sources/jira_{k}_state_at_cutoff.json"]
        rebuilt = reconstruct_at(issue, cutoff)
        jira_links.append(entry | {"requirement_quality": classify_issue(issue, cutoff), "source": rebuilt["source"],
                                   "reconstruction_status": rebuilt["status"], "state_at_cutoff": state_summary(state)})
    jira_links = sort_links(jira_links)

    hist = pin(repo, merge_sha, n, data["files"], api_base=pr["base"]["sha"], api_head=pr["head"]["sha"])
    dump_json(src / "history.json", hist)
    base, head, merge_base = hist["base_at_merge"], hist["head_at_merge"], hist["merge_base_sha"]
    # CODEOWNERS on the base branch at the merge (base_at_merge), never at GitHub's API base
    co_path, co_text = codeowners_at(repo, base) if base else (None, None)
    (src / "CODEOWNERS_at_base.txt").write_text(co_text if co_text is not None else "NO CODEOWNERS FILE AT BASE\n", encoding="utf-8")
    policy_path, policy_sha, policy_status = policy_for(cfg["name"])
    # the exact policy bytes, so the case can be rerun with the policy it was frozen under (audit 21 Nov)
    shutil.copyfile(policy_path, case_dir / POLICY_SNAPSHOT)
    if sha256_file(case_dir / POLICY_SNAPSHOT) != policy_sha:
        raise SystemExit(f"{cid}: the policy file changed while freezing; run again")
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (src / "fetched_at.txt").write_text(fetched + "\n", encoding="utf-8")

    (case_dir / "case.yaml").write_text(
        (TEMPLATES / "case.yaml").read_text(encoding="utf-8").format(
            case_id=cid, set=row["set"], repo=cfg["github"], pr_number=n, pr_url=pr["html_url"], cutoff=cutoff,
            merge_commit_sha=hist["merge_commit_sha"], merge_strategy=hist["merge_strategy"] or "unknown",
            base_at_merge=base or "unknown", head_at_merge=head or "unknown", merge_base_sha=merge_base or "unknown",
            historical_diff_status=hist["historical_diff_status"],
            historical_diff_reason=hist["historical_diff_reason"].replace('"', "'"),
            historical_content_status=hist.get("historical_content_status", "not_checked"),
            historical_content_reason=hist.get("historical_content_reason", "").replace('"', "'"),
            case_group=row.get("case_group") or group_of(load_groups(), cfg["name"], n),
            api_base_sha=hist["api_base_sha"], api_head_sha=hist["api_head_sha"],
            jira_keys=", ".join(keys) or "none", jira_links=jira_links_yaml(jira_links),
            policy_sha256=policy_sha, policy_status=policy_status.replace('"', "'"), policy_file=f"eval/policies/{cfg['name']}.yaml",
            analysis_root=cfg["analysis_root"] or "/", codeowners=co_path or "none", fetched_at=fetched,
            category=row["category_provisional"]),
        encoding="utf-8")
    row.update({"decision_cutoff_utc": cutoff, "base_sha": base, "head_sha": head, "merge_base_sha": merge_base,
                "policy_file": f"eval/policies/{cfg['name']}.yaml"})
    print(f"{cid}: collected #{n} ({len(data['files'])} files, {len(data['reviews'])} reviews by the cutoff, "
          f"{len(data['reviews_post_cutoff'])} after, keys {keys or 'none'})")
    refs = {"policy_sha256": policy_sha}
    refs |= {k: hist.get(k, "") for k in ("merge_commit_sha", "merge_strategy", "base_at_merge", "head_at_merge",
                                         "merge_base_sha", "historical_diff_status", "historical_content_status",
                                         "api_base_sha", "api_head_sha")}
    return {"mandatory": mandatory, "refs": refs}


# ---------------------------------------------------------------- freeze


def out_root_for(row: dict[str, str], out: Path | None) -> Path:
    if out is not None:
        return out
    return EVAL / {"challenge": "challenge", "dev": "dev_cases"}.get(row["set"], "cases")


def latest_invalid(root: Path, cid: str) -> Path | None:
    """The newest <cid>.invalid-<stamp>/ folder that still holds annotator files, if any.

    If a refreeze crashed after the old folder was moved aside, the next run takes the labels from there.
    """
    found = sorted((p for p in root.glob(f"{cid}.invalid-*") if p.is_dir()
                    and any((p / n).is_file() for n in ANNOTATOR_FILES)), key=lambda p: p.name)
    return found[-1] if found else None


def labelled(path: Path, template: Path) -> bool:
    """True if an annotator file holds more than its blank template."""
    return path.is_file() and path.read_bytes() != template.read_bytes()


def template_for(name: str) -> Path:
    return TEMPLATES / ("label.yaml" if name.startswith("label_") else name)


def evidence_changes(old_dir: Path, new_dir: Path) -> list[str]:
    """Frozen files whose content differs between an old freeze and the new one (fetched_at.txt ignored)."""
    try:
        old = json.loads((old_dir / MANIFEST).read_text(encoding="utf-8")).get("files", {})
    except (OSError, json.JSONDecodeError):
        return ["the old freeze had no readable manifest, so its evidence cannot be compared"]
    new = {rel: sha256_file(new_dir / rel) for rel in frozen_files(new_dir)}
    skip = {"sources/fetched_at.txt"}
    return sorted(r for r in (set(old) | set(new)) - skip if old.get(r) != new.get(r))


def freeze(row: dict[str, str], out: Path | None = None, refresh: bool = False, allow_draft: bool = False) -> str:
    """Freeze one case; returns 'skipped' (already complete) or 'frozen'."""
    cid = row["case_id"]
    policy_for(row["repo"])   # B5: no policy, no freeze; checked before anything is moved or written
    check_policy_gate(row, allow_draft)
    root = out_root_for(row, out)
    final = root / cid
    carried: Path | None = latest_invalid(root, cid) if root.exists() and not final.exists() else None
    if final.exists():
        reasons = verify_case(final)
        if not reasons and not refresh:
            print(f"{cid}: complete freeze verified, skipping (use --refresh to freeze again)")
            return "skipped"
        carried = root / f"{cid}.invalid-{_stamp()}"
        n = 1
        while carried.exists():  # two refreezes in the same second
            n += 1
            carried = root / f"{cid}.invalid-{_stamp()}-{n}"
        _replace_dir(final, carried)
        (carried / "REASON.txt").write_text("\n".join(reasons or ["--refresh requested"]) + "\n", encoding="utf-8")
        print(f"{cid}: moved to {carried.name} ({'; '.join(reasons) or '--refresh'})")

    staging = root / f"{cid}.staging"
    if staging.exists():
        shutil.rmtree(staging)  # left by an interrupted run: never trusted
    staging.mkdir(parents=True)
    info = collect(row, staging)
    kept = []
    for name in ANNOTATOR_FILES:  # keep what annotators wrote; blank templates only for new files
        old = carried / name if carried else None
        if old is not None and old.is_file():
            shutil.copy2(old, staging / name)
            if labelled(old, template_for(name)):
                kept.append(name)
        else:
            shutil.copy(template_for(name), staging / name)
    (staging / "run").mkdir(exist_ok=True)
    (staging / "run" / ".gitkeep").touch()
    write_manifest(staging, MANDATORY + info["mandatory"], info["refs"])
    if carried is not None and kept:
        old_stale = stale_note(carried)
        changed = evidence_changes(carried, staging)
        if changed or old_stale:
            lines = [f"Labels carried over from {carried.name} on {_stamp()} were made on different evidence or policy.",
                     "Review and relabel these files before they count; then delete this file.",
                     f"Carried label files: {', '.join(kept)}",
                     *(f"Changed: {c}" for c in changed[:50])]
            if old_stale:
                lines.append(f"Already stale before this refreeze: {old_stale.splitlines()[0]}")
            (staging / STALE).write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"{cid}: labels carried over are STALE ({len(changed)} evidence files changed): see {STALE}")
    _replace_dir(staging, final)
    print(f"{cid}: frozen into {final}")
    return "frozen"


def case_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and ".staging" not in p.name and ".invalid-" not in p.name
                  and not p.name.startswith("."))


def verify(roots: list[Path], case_id: str | None) -> int:
    bad = 0
    dirs = [r / case_id for r in roots] if case_id else [d for r in roots if r.exists() for d in case_dirs(r)]
    if case_id:
        dirs = [d for d in dirs if d.exists()] or dirs[:1]
    stale = 0
    for d in dirs:
        reasons = verify_case(d)
        note = stale_note(d) if d.is_dir() else None
        print(f"{d.name}: {'OK' if not reasons else 'INVALID'}{' (labels STALE: relabel before use)' if note else ''}")
        for r in reasons:
            print(f"  - {r}")
        bad += bool(reasons)
        stale += bool(note)
    print(f"\n{len(dirs) - bad} OK, {bad} INVALID, {stale} with stale labels")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--case")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--verify", action="store_true", help="check frozen cases (all, or --case ID); fetches nothing")
    ap.add_argument("--refresh", action="store_true", help="freeze again even if the case is complete")
    ap.add_argument("--allow-draft", action="store_true",
                    help="freeze under a DRAFT policy (engineering freeze, repeated after sign-off)")
    ap.add_argument("--cases", type=Path, default=EVAL / "cases.csv", help="cases file (default eval/cases.csv)")
    ap.add_argument("--out", type=Path, help="folder for the frozen cases (default eval/cases, eval/challenge)")
    a = ap.parse_args(argv)

    if a.verify:
        roots = [a.out] if a.out else [EVAL / "cases", EVAL / "dev_cases", EVAL / "challenge"]
        return verify(roots, a.case)
    if not (a.case or a.all):
        ap.error("give --case ID, --all or --verify")

    path = a.cases
    fields = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    rows = read_csv(path)
    todo = rows if a.all else [r for r in rows if r["case_id"] == a.case]
    if not todo:
        raise SystemExit(f"case {a.case} not in {path}")
    for r in todo:
        freeze(r, a.out, a.refresh, a.allow_draft)
        write_csv(path, rows, fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
