"""Neutral annotation packets for frozen cases (audit 21 Nov, Day 4 point 8): <case>/packet/.

The packet is what a labeller works from for the semantic labels: the case's acceptance criteria (criteria.csv)
and every function, method and class at the case's head (entities.csv). No CodeAtlas ranking or score is in it,
so labelling from it stays blind to CodeAtlas output.

It is built with CodeAtlas's own scripts/prepare_case.py (branch feature/semantic-retrieval), so the criterion ids
(KEY:vN:acM) are the ones a CodeAtlas run produces and labels join runs on the same id. That tool takes one key
and plain issue text, and overwrites criteria.csv on every run. This script therefore:

1. takes each key of the case whose link is verified and whose cutoff file carries text (or only the keys given
   with --keys, once the team has adjudicated relevance), and skips the rest with the reason;
2. strips the metadata header of sources/jira_<KEY>_at_cutoff.txt (everything up to the first '---' line), so the
   header is never split into criteria;
3. runs prepare_case.py once per key, each into its own temporary folder;
4. merges the criteria.csv files (key order; a criterion id seen twice is an error) and keeps one entities.csv,
   checking that every run wrote the same bytes (they must: same repo, same SHA, same root);
5. writes packet/criteria.csv, packet/entities.csv, packet/issue_text_<KEY>.txt (the exact text given to the tool)
   and packet/PACKET.json (head SHA, analysis root, keys used and skipped, requirement version, the sha256 of
   prepare_case.py and the CodeAtlas commit), and refuses to overwrite an existing packet without --force.

entities.csv lists the code at head_at_merge. Code the PR deleted is not there, so it cannot be a candidate entity;
the guide says how to label a criterion that the PR met by deleting code (LABELLING_GUIDE, semantic labels).
packet/ is not in the case manifest: it is derived from frozen sources and can be rebuilt; freeze_case.py --verify
does not check it.

Usage (Windows, from the dataset repo):
    git -C D:\\codeatlas worktree add D:\\codeatlas-semantic origin/feature/semantic-retrieval
    python scripts/prepare_packets.py --codeatlas D:\\codeatlas-semantic eval\\dev_cases\\AF-D01
    python scripts/prepare_packets.py --codeatlas D:\\codeatlas-semantic --keys AIRFLOW-5490 eval\\cases\\AF-01
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import REPOS_DIR, load_repos

PACKET = "packet"
TEXT_STATUSES = ("reconstructed", "created_text_only")
CRITERIA_COLUMNS = ["criterion_id", "key", "version_no", "criterion_text"]


def case_field(case_yaml: str, name: str) -> str:
    """A top-level scalar of case.yaml (written by freeze_case.py from a fixed template, so a line match is safe)."""
    m = re.search(rf"^{re.escape(name)}:[ \t]*(.*?)[ \t]*(?:#.*)?$", case_yaml, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else ""


def split_cutoff_file(text: str) -> tuple[dict[str, str], str]:
    """(header fields, plain issue text) of a jira_<KEY>_at_cutoff.txt. The header ends at the first '---' line."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\r\n") == "---":
            header = dict(x.split(":", 1) for x in "".join(lines[:i]).splitlines() if ":" in x)
            return {k.strip(): v.strip() for k, v in header.items()}, "".join(lines[i + 1:])
    raise ValueError("no '---' line: not a cutoff file written by freeze_case.py")


def keys_to_use(case_dir: Path, wanted: list[str] | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """([{key, text}] to prepare, [{key, reason}] skipped)."""
    links = json.loads((case_dir / "sources" / "jira_links.json").read_text(encoding="utf-8"))["links"]
    status = {x["key"]: x["status"] for x in links}
    frozen = sorted(p.name[len("jira_"):-len("_at_cutoff.txt")] for p in (case_dir / "sources").glob("jira_*_at_cutoff.txt"))
    use, skip = [], []
    for k in wanted or frozen:
        path = case_dir / "sources" / f"jira_{k}_at_cutoff.txt"
        if not path.exists():
            raise SystemExit(f"{case_dir.name}: {k} has no frozen cutoff file (keys of this case: {', '.join(frozen)})")
        header, text = split_cutoff_file(path.read_text(encoding="utf-8"))
        rs = header.get("reconstruction_status", "")
        if status.get(k) != "verified" and not wanted:
            skip.append({"key": k, "reason": f"link status {status.get(k, 'unknown')} (only verified keys are scored)"})
        elif rs not in TEXT_STATUSES:
            skip.append({"key": k, "reason": f"no issue text at the cutoff (reconstruction_status {rs or 'unknown'})"})
        elif not text.strip():
            skip.append({"key": k, "reason": "the issue text at the cutoff is empty"})
        else:
            use.append({"key": k, "text": text, "reconstruction_status": rs})
    return use, skip


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def codeatlas_commit(codeatlas: Path) -> str:
    res = subprocess.run(["git", "-C", str(codeatlas), "rev-parse", "HEAD"], capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else "unknown"


def clone_for(case_yaml: str, clone: Path | None) -> Path:
    if clone:
        return clone
    github = case_field(case_yaml, "repo")
    for cfg in load_repos().values():
        if cfg["github"] == github:
            return REPOS_DIR / cfg["name"]
    raise SystemExit(f"repo {github!r} of case.yaml is not in eval/repos.json; give --clone")


def build(case_dir: Path, codeatlas: Path, prepare_cmd: list[str], clone: Path | None = None,
          wanted: list[str] | None = None, version: int = 1, force: bool = False) -> dict:
    case_yaml = (case_dir / "case.yaml").read_text(encoding="utf-8")
    head = case_field(case_yaml, "head_at_merge")
    root = case_field(case_yaml, "analysis_root").strip("/")
    out = case_dir / PACKET
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise SystemExit(f"{case_dir.name}: head_at_merge {head!r} in case.yaml is not a full SHA")
    if out.exists() and not force:
        raise SystemExit(f"{out} exists; give --force to rebuild it. Nothing written.")
    use, skip = keys_to_use(case_dir, wanted)
    if not use:
        raise SystemExit(f"{case_dir.name}: no key to prepare ("
                         + "; ".join(f"{s['key']}: {s['reason']}" for s in skip) + "). Nothing written.")
    repo = clone_for(case_yaml, clone)
    script = codeatlas / "scripts" / "prepare_case.py"

    criteria: list[dict[str, str]] = []
    entities: bytes | None = None
    logs = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for u in use:
            k = u["key"]
            text_file, run_dir = tmp / f"issue_{k}.txt", tmp / k
            text_file.write_text(u["text"], encoding="utf-8")
            cmd = [*prepare_cmd, "--repo", f"{repo}@{head}", "--key", k, "--version", str(version),
                   "--issue-text", str(text_file), "--root", root, "--out", str(run_dir)]
            res = subprocess.run(cmd, cwd=codeatlas, capture_output=True, text=True, encoding="utf-8", errors="replace")
            logs[k] = res.stdout.strip()
            if res.returncode != 0 and not (run_dir / "criteria.csv").exists():
                raise SystemExit(f"{case_dir.name}: prepare_case.py failed for {k} (exit {res.returncode}):\n"
                                 f"{res.stdout}{res.stderr}\nNothing written.")
            got = read_rows(run_dir / "criteria.csv")
            if not got:
                skip.append({"key": k, "reason": "prepare_case.py found no acceptance criteria in the issue text"})
                continue
            criteria += got
            ent = (run_dir / "entities.csv").read_bytes()
            if entities is not None and ent != entities:
                raise SystemExit(f"{case_dir.name}: entities.csv for {k} differs from the first key's; the runs did not "
                                 "read the same code. Nothing written.")
            entities = ent
            u["criteria"] = len(got)
        ids = [c["criterion_id"] for c in criteria]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise SystemExit(f"{case_dir.name}: criterion ids seen twice: {', '.join(dupes)}. Nothing written.")
        if entities is None:
            raise SystemExit(f"{case_dir.name}: no key gave any criteria ("
                             + "; ".join(f"{s['key']}: {s['reason']}" for s in skip) + "). Nothing written.")

        staging = case_dir / f".{PACKET}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CRITERIA_COLUMNS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(criteria)
        (staging / "criteria.csv").write_text(buf.getvalue(), encoding="utf-8", newline="")
        (staging / "entities.csv").write_bytes(entities)
        for u in use:
            if u.get("criteria"):
                (staging / f"issue_text_{u['key']}.txt").write_text(u["text"], encoding="utf-8", newline="")
    meta = {
        "case_id": case_field(case_yaml, "case_id"), "head_at_merge": head, "analysis_root": root or "/",
        "requirement_version": version,
        "keys_used": [{"key": u["key"], "reconstruction_status": u["reconstruction_status"], "criteria": u["criteria"]}
                      for u in use if u.get("criteria")],
        "keys_skipped": skip,
        "entities": len(list(csv.DictReader(io.StringIO(entities.decode("utf-8"))))),
        "prepare_case_sha256": sha256(script) if script.exists() else "unknown",
        "codeatlas_commit": codeatlas_commit(codeatlas),
        "deleted_code": "entities are the code at head_at_merge; code the PR deleted is not a candidate",
        "prepare_case_output": logs,
    }
    (staging / "PACKET.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if out.exists():
        shutil.rmtree(out)
    staging.replace(out)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+", type=Path, help="frozen case folders, e.g. eval/dev_cases/AF-D01")
    ap.add_argument("--codeatlas", type=Path, required=True,
                    help="a CodeAtlas checkout of feature/semantic-retrieval (has scripts/prepare_case.py)")
    ap.add_argument("--prepare-cmd", default="",
                    help="command that runs prepare_case.py (default: uv run python scripts/prepare_case.py, "
                         "run inside --codeatlas)")
    ap.add_argument("--clone", type=Path, help="clone of the case's repository (default eval/repos/<name>)")
    ap.add_argument("--keys", nargs="+", help="only these keys (after relevance adjudication)")
    ap.add_argument("--version", type=int, default=1, help="requirement version passed to prepare_case.py")
    ap.add_argument("--force", action="store_true", help="rebuild an existing packet/")
    a = ap.parse_args(argv)
    cmd = shlex.split(a.prepare_cmd) if a.prepare_cmd else ["uv", "run", "python", "scripts/prepare_case.py"]
    for case_dir in a.cases:
        m = build(case_dir, a.codeatlas, cmd, a.clone, a.keys, a.version, a.force)
        used = ", ".join(f"{k['key']} ({k['criteria']} criteria)" for k in m["keys_used"])
        skipped = "; ".join(f"{s['key']}: {s['reason']}" for s in m["keys_skipped"]) or "none"
        print(f"{case_dir.name}: {m['entities']} entities at {m['head_at_merge'][:12]}, root {m['analysis_root']}; "
              f"keys {used}; skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
