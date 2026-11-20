"""Read Apache Jira issues from the public mailing-list archive (lists.apache.org).

Apache Jira (issues.apache.org) now asks for a login, even to read, and public sign-up is closed.
Every Apache project's Jira, however, emailed each new issue and each edit to a public list
(Airflow: commits@, Spark/Arrow/Beam: issues@). Those emails are kept at lists.apache.org.

This module rebuilds the part of a Jira issue the dataset needs from those emails:
- the summary and the description as written when the issue was created ("[jira] [Created]" email),
- every later summary/description edit with its time ("[jira] [Updated]" emails),
in the same shape as the Jira REST API (`fields`, `changelog.histories`), so build_pool.py and
freeze_case.py use it unchanged. The result says where it came from (`source`, `archive`).

Limits: an edit is recorded with the new text only (the emails do not always carry the old text);
issues whose emails never reached the list are reported as not found, never guessed.

Every issue records where it came from in `source`: "apache_mail_archive" (this module) or "jira_rest"
(Jira's REST API). The text at a cutoff is rebuilt differently for each (`reconstruct_at`):
- archive: the created text plus every edit up to the cutoff (edits after it are ignored);
- REST: the current text with every summary/description edit after the cutoff undone, newest first, using
  each edit's old value (`fromString`). An edit without an old value makes the result "unverifiable".
"""

from __future__ import annotations

import email
import email.policy
import re
import time
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

ARCHIVE_API = "https://lists.apache.org/api"
DEFAULT_LISTS = ("issues", "commits", "jira", "dev")
SOURCE = "apache_mail_archive"   # the issue was rebuilt from lists.apache.org (Jira notification emails)
REST_SOURCE = "jira_rest"         # the issue came from Jira's REST API (current text plus changelog)
TRACKED_FIELDS = ("summary", "description")
TRAILER = re.compile(r"\n--\s*\nThis message was sent by Atlassian.*", re.DOTALL)
SUBJECT = re.compile(r"^\[jira\]\s+\[(?P<kind>[^\]]+)\]\s+\((?P<key>[A-Z][A-Z0-9_]*-\d+)\)\s*(?P<title>.*)$", re.DOTALL)
HEADER_LINE = re.compile(r"^\s*(?P<name>[A-Z][A-Za-z /]*?):\s?(?P<value>.*)$")
UPDATED_FIELD = re.compile(r"^\s{2,}(?P<name>Summary|Description):\s?(?P<value>.*)$")
HEADER_NAMES = {
    "Summary", "Key", "URL", "Project", "Issue Type", "Components", "Component/s", "Affects Versions",
    "Affects Version/s", "Fix Versions", "Fix Version/s", "Reporter", "Assignee", "Priority", "Labels",
    "Environment", "Original Estimate", "Remaining Estimate", "Attachments", "Issue Links", "Sub-tasks",
    "Epic Link", "Sprint", "Status", "Resolution", "Security Level",
}

Getter = Callable[[str], Any]


class NotInArchive(LookupError):
    """No '[jira] [Created]' email for this key in any of the lists searched."""


def project_domain(key: str) -> str:
    """AIRFLOW-5477 -> airflow.apache.org"""
    return f"{key.split('-', 1)[0].lower()}.apache.org"


def jira_time(epoch: float) -> str:
    """Epoch seconds -> Jira's own timestamp format, which build_pool.py already parses."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_subject(subject: str) -> tuple[str, str, str] | None:
    """'[jira] [Created] (AIRFLOW-1) Title' -> ('Created', 'AIRFLOW-1', 'Title')"""
    m = SUBJECT.match(_one_line(subject))
    return (m["kind"], m["key"], m["title"].strip()) if m else None


def _body_lines_after_rule(body: str) -> list[str]:
    """Lines after the '-----' rule under 'X created/updated KEY:', trailer removed."""
    text = TRAILER.sub("", body.replace("\r\n", "\n"))
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^-{5,}\s*$", line):
            return lines[i + 1:]
    return lines


def parse_created(body: str) -> dict[str, str]:
    """Header fields (Summary, Key, Issue Type, ...) and the description of a Created email."""
    lines = _body_lines_after_rule(body)
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    fields: dict[str, str] = {}
    last = ""
    while i < len(lines) and lines[i].strip():
        m = HEADER_LINE.match(lines[i])
        if m and m["name"].strip() in HEADER_NAMES:
            last = m["name"].strip()
            fields[last] = m["value"].strip()
        elif last:  # a long header value wrapped onto the next line
            fields[last] = (fields[last] + " " + lines[i].strip()).strip()
        i += 1
    fields["Description"] = "\n".join(lines[i:]).strip("\n").rstrip()
    return fields


def parse_updated(body: str) -> list[dict[str, str]]:
    """Summary/description changes in an Updated email, as Jira changelog items (new text only)."""
    lines = _body_lines_after_rule(body)
    items: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        m = UPDATED_FIELD.match(lines[i])
        if not m:
            i += 1
            continue
        name = m["name"]
        if name == "Summary":
            value = re.sub(r"\s*\(was:.*\)\s*$", "", m["value"]).strip()
            items.append({"field": "summary", "toString": value})
            i += 1
            continue
        # Description: the new text follows until the next indented 'Field:' line or the end
        block = [m["value"]] if m["value"].strip() else []
        i += 1
        while i < len(lines) and not re.match(r"^\s{2,}[A-Z][A-Za-z /]*:\s", lines[i]):
            block.append(lines[i])
            i += 1
        items.append({"field": "description", "toString": "\n".join(block).strip()})
    return items


def _search(get: Getter, key: str, lst: str, domain: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"list": lst, "domain": domain, "d": "lte=25y", "q": key})
    data = get(f"{ARCHIVE_API}/stats.lua?{query}") or {}
    return list(data.get("emails") or [])


def _full_body(get: Getter, mid: str) -> str:
    """Whole email body: email.lua JSON, else the raw message from source.lua."""
    try:
        data = get(f"{ARCHIVE_API}/email.lua?id={urllib.parse.quote(mid)}")
        if isinstance(data, dict) and data.get("body"):
            return str(data["body"])
    except Exception as e:  # noqa: BLE001 - fall through to the raw source
        print(f"  archive: email.lua failed for {mid} ({e}); using the raw message")
    raw = get(f"{ARCHIVE_API}/source.lua?id={urllib.parse.quote(mid)}")
    msg = email.message_from_string(raw if isinstance(raw, str) else str(raw), policy=email.policy.default)
    part = msg.get_body(preferencelist=("plain",)) if msg.is_multipart() else msg
    return part.get_content() if part is not None else ""


def archive_issue(key: str, get: Getter, lists: tuple[str, ...] = DEFAULT_LISTS, domain: str | None = None,
                  pause: float = 0.2) -> dict[str, Any]:
    """Rebuild one Jira issue from the archive, Jira REST shaped. Raises NotInArchive if absent."""
    domain = domain or project_domain(key)
    for lst in lists:
        seen: set[str] = set()
        created: dict[str, Any] | None = None
        updates: list[dict[str, Any]] = []
        for e in _search(get, key, lst, domain):
            parsed = parse_subject(e.get("subject", ""))
            msg_id = e.get("message-id") or e.get("mid") or e.get("id")
            if not parsed or parsed[1] != key or msg_id in seen:
                continue
            seen.add(msg_id)
            if parsed[0] == "Created" and (created is None or e["epoch"] < created["epoch"]):
                created = e
            elif parsed[0] == "Updated":
                updates.append(e)
        if created is None:
            continue

        time.sleep(pause)
        fields = parse_created(_full_body(get, created["mid"]))
        histories = []
        for u in sorted(updates, key=lambda x: x["epoch"]):
            time.sleep(pause)
            items = parse_updated(_full_body(get, u["mid"]))
            if items:
                histories.append({"created": jira_time(u["epoch"]), "items": items, "archive_mid": u["mid"]})
        summary = fields.get("Summary") or parse_subject(created["subject"])[2]  # type: ignore[index]
        return {
            "key": key,
            "source": SOURCE,
            "archive": {"list": f"{lst}@{domain}", "created_mid": created["mid"],
                        "updated_mids": [h["archive_mid"] for h in histories],
                        "permalink": f"https://lists.apache.org/thread/{created['mid']}"},
            "fields": {
                "summary": summary,
                "description": fields.get("Description", ""),
                "created": jira_time(created["epoch"]),
                "issuetype": {"name": fields.get("Issue Type", "")},
                "components": [{"name": c.strip()} for c in fields.get("Components", "").split(",") if c.strip()],
                "reporter": {"displayName": fields.get("Reporter", "")},
            },
            "changelog": {"histories": histories},
        }
    raise NotInArchive(f"{key}: no '[jira] [Created]' email in {', '.join(lists)} @ {domain}")


def description_at(issue: dict[str, Any], cutoff_iso: str) -> tuple[str, str]:
    """(summary, description) as they stood at the cutoff: created text plus edits up to the cutoff."""
    cutoff = datetime.fromisoformat(cutoff_iso.replace("Z", "+00:00"))
    summary = issue["fields"].get("summary", "")
    description = issue["fields"].get("description", "") or ""
    for h in sorted(issue.get("changelog", {}).get("histories", []), key=lambda h: _at(h["created"])):
        at = _at(h["created"])
        if at > cutoff:
            break
        for item in h.get("items", []):
            if item.get("field") == "summary":
                summary = item.get("toString", summary)
            elif item.get("field") == "description":
                description = item.get("toString", description)
    return summary, description


def issue_source(issue: dict[str, Any]) -> str:
    """apache_mail_archive or jira_rest. Older saved issues: an `archive` block means the mail archive."""
    src = issue.get("source") or ""
    if src == SOURCE or src.startswith("lists.apache.org") or "archive" in issue:
        return SOURCE
    if src == REST_SOURCE or (not src and "fields" in issue):
        return REST_SOURCE
    return src or "unknown"


def _at(created: str) -> datetime:
    return datetime.fromisoformat(created.replace("Z", "+00:00").replace("+0000", "+00:00"))


def reconstruct_at(issue: dict[str, Any], cutoff_iso: str) -> dict[str, str]:
    """Summary and description as they stood at the cutoff, with how they were obtained.

    Returns source, cutoff, status ("reconstructed" or "unverifiable"), note, summary, description.
    An unverifiable result has empty text: it is never filled with a guess.
    """
    source = issue_source(issue)
    cutoff = _at(cutoff_iso)
    out = {"source": source, "cutoff": cutoff_iso, "status": "reconstructed", "note": "", "summary": "", "description": ""}
    histories = sorted(issue.get("changelog", {}).get("histories", []), key=lambda h: _at(h["created"]))
    tracked = [(h, i) for h in histories for i in h.get("items", []) if i.get("field") in TRACKED_FIELDS]
    later = [(h, i) for h, i in tracked if _at(h["created"]) > cutoff]
    if source == SOURCE:
        out["summary"], out["description"] = description_at(issue, cutoff_iso)
        n_later = len({id(h) for h, _ in later})
        n_all = len({id(h) for h, _ in tracked})
        out["note"] = (f"created text plus {n_all - n_later} archived edit(s) up to the cutoff; "
                       f"{n_later} later edit(s) ignored")
        return out
    if source == REST_SOURCE:
        summary = issue.get("fields", {}).get("summary", "") or ""
        description = issue.get("fields", {}).get("description", "") or ""
        for h, item in reversed(later):  # newest first
            if item.get("fromString") is None:
                out.update(status="unverifiable",
                           note=f"{item['field']} edit at {h['created']} has no old value (fromString); text not rebuilt")
                return out
            if item["field"] == "summary":
                summary = item["fromString"]
            else:
                description = item["fromString"]
        out.update(summary=summary, description=description,
                   note=f"current text with {len({id(h) for h, _ in later})} later edit(s) undone using fromString")
        return out
    out.update(status="unverifiable", note=f"unknown source '{source}'")
    return out


def cutoff_file_text(issue: dict[str, Any], cutoff_iso: str) -> str:
    """Contents of jira_<KEY>_at_cutoff.txt: a header (source, cutoff, status), a '---' line, then the text.

    Readers take the issue text from after the first '---' line. An unverifiable issue has no text.
    """
    r = reconstruct_at(issue, cutoff_iso)
    header = (f"key: {issue.get('key', '')}\nsource: {r['source']}\ncutoff: {r['cutoff']}\n"
              f"reconstruction_status: {r['status']}\nreconstruction_note: {r['note']}\n---\n")
    if r["status"] != "reconstructed":
        return header
    return header + f"{r['summary']}\n\n{r['description']}".rstrip() + "\n"


def issue_text(issue: dict[str, Any], cutoff_iso: str | None = None) -> str:
    """Plain text for scripts/prepare_case.py --issue-text: summary line, blank line, description."""
    if cutoff_iso:
        summary, description = description_at(issue, cutoff_iso)
    else:
        summary, description = issue["fields"].get("summary", ""), issue["fields"].get("description", "") or ""
    return f"{summary}\n\n{description}".rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Check one key by hand: python scripts/jira_archive.py AIRFLOW-5477"""
    import argparse
    import json

    from common import archive_get

    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--json", action="store_true", help="print the whole rebuilt issue")
    a = ap.parse_args(argv)
    try:
        issue = archive_issue(a.key, archive_get)
    except NotInArchive as e:
        print(e)
        return 1
    if a.json:
        print(json.dumps(issue, indent=2, ensure_ascii=False))
        return 0
    print(f"source: {issue['archive']['list']} ({issue['archive']['permalink']})")
    print(f"created: {issue['fields']['created']}   edits to summary/description: {len(issue['changelog']['histories'])}")
    print("-" * 60)
    print(issue_text(issue))
    return 0


__all__ = ["NotInArchive", "archive_issue", "cutoff_file_text", "description_at", "issue_source", "issue_text",
           "parse_created", "parse_subject", "parse_updated", "project_domain", "reconstruct_at"]


if __name__ == "__main__":
    raise SystemExit(main())
