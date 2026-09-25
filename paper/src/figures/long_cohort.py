"""The four-hour sessions that count, selected by the reviewed manifest.

The catalogue at the four-hour budget is an archive of attempts, including
retries and interrupted runs. A session counts when the service ended it at the
budget and its last key falls within the final fifteen minutes. The manifest
lists every attempt with its status and reason, and validation refuses an
attempt the manifest does not list.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "long_submissions.json"
STATUSES = {"selected", "stopped_early", "startup_only",
            "no_actions", "incompatible_config", "protocol_violation"}


def last_key_seconds(row, timeline_dir=None):
    """Time of the last recorded key, on the replay's service-time scale."""
    directory = Path(timeline_dir) if timeline_dir is not None else HERE / "timelines"
    path = directory / (row["id"] + ".json")
    if not path.exists():
        if not row.get("actions"):
            return 0.0
        raise ValueError("missing timeline: " + row["id"])
    timeline = json.loads(path.read_text(encoding="utf-8"))
    marks = timeline["marks"]
    return float(marks[-1]["t"] * timeline["speed"]) if marks else 0.0


def validate(rows, manifest=None, timeline_dir=None):
    """Refuse an attempt the manifest does not list, a duplicate id, a stale
    model mapping, or a status that disagrees with the rule. Rows carry the
    canonical ``agent`` and the ``declared`` name. Returns the manifest."""
    if manifest is None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or manifest.get("state") != "reviewed":
        raise ValueError("unsupported submission manifest version/state")
    budget = manifest["budget_seconds"]
    window = manifest["last_key_window_seconds"]
    if budget != 14400 or window != 900:
        raise ValueError("the rule is a 240-minute budget and a fifteen-minute window")
    ids = [r["id"] for r in rows]
    entries = manifest["attempts"]
    entry_ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)) or len(entry_ids) != len(set(entry_ids)):
        raise ValueError("duplicate session ID")
    if set(ids) != set(entry_ids):
        raise ValueError("submission manifest does not cover the four-hour archive exactly")
    indexed = {r["id"]: r for r in rows}
    blocked = set(manifest["protocol_violations"])
    incompatible = set(manifest["incompatible_declared_names"])
    selected = set()
    for entry in entries:
        r = indexed[entry["id"]]
        if r["budget"] != budget:
            raise ValueError("wrong budget: " + r["id"])
        if (entry["model"], entry["declared_model"]) != (r["agent"], r["declared"]):
            raise ValueError("stale model mapping: " + r["id"])
        status = entry["status"]
        if status not in STATUSES or not entry.get("reason"):
            raise ValueError("missing status or explanation: " + r["id"])
        if r["id"] in blocked:
            expected = "protocol_violation"
        elif r["declared"] in incompatible:
            expected = "incompatible_config"
        elif not r.get("actions"):
            expected = "no_actions"
        elif r["actions"] <= 2:
            expected = "startup_only"
        elif r.get("reason") == "time" and budget - window <= last_key_seconds(r, timeline_dir) <= budget:
            expected = "selected"
        else:
            expected = "stopped_early"
        if status != expected:
            raise ValueError("status disagrees with the rule: " + r["id"])
        if status == "selected":
            selected.add(r["id"])
    if not selected:
        raise ValueError("no four-hour session counts")
    return manifest


def select(rows, manifest=None, timeline_dir=None):
    manifest = validate(rows, manifest, timeline_dir)
    ids = {e["id"] for e in entries_of(manifest, "selected")}
    return [r for r in rows if r["id"] in ids]


def entries_of(manifest, status):
    return [e for e in manifest["attempts"] if e["status"] == status]
