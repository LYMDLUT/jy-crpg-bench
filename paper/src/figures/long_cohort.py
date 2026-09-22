"""Select four-hour sessions from the reviewed attempt manifest.

A time-ended session needs near-deadline keys or reviewed client evidence of
continued activity until expiry. Last key is not client runtime. Startup,
configuration and protocol exclusions still take precedence. The archive is
unchanged, and evidence is checked against each specific recorded attempt.
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


def verified_client_completion(row, entry):
    """Validate a reviewed attestation, not a catalogue time/valid flag alone.

    This checks the published evidence structure and its match to the archive;
    it does not pretend to replay or automatically certify private transcripts.
    No model name or session ID is special-cased here.
    """
    evidence = entry.get("client_completion")
    if evidence is None:
        return False
    if not isinstance(evidence, dict):
        raise ValueError("invalid client completion evidence: " + row["id"])
    response = evidence.get("response", {})
    matches = (
        evidence.get("reviewed") is True
        and evidence.get("session_id") == row["id"]
        and evidence.get("budget_seconds") == row["budget"]
        and evidence.get("activity_until_expiry") is True
        and evidence.get("human_intervention_observed") is False
        and bool(evidence.get("source"))
        and bool(evidence.get("reference"))
        and evidence.get("http_status") == 410
        and isinstance(response, dict)
        and response.get("agent") == row["declared"]
        and response.get("actions") == row["actions"]
        and response.get("reason") == row.get("reason") == "time"
        and response.get("why") == "the full %d minutes budget was used" % (row["budget"] // 60)
        and response.get("ended") is True
        and response.get("error", "missing") is None
    )
    if not matches:
        raise ValueError("unreviewed or mismatched client completion evidence: " + row["id"])
    return True


def validate(rows, manifest=None, timeline_dir=None):
    """Refuse unlisted IDs, stale mappings, bad evidence and wrong statuses."""
    if manifest is None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or manifest.get("state") != "reviewed":
        raise ValueError("unsupported submission manifest version/state")
    budget = manifest["budget_seconds"]
    window = manifest["last_key_window_seconds"]
    if budget != 14400 or window != 120:
        raise ValueError("the budget is 240 minutes; the last-key evidence window is two minutes")
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
        client_completed = verified_client_completion(r, entry)
        if r["id"] in blocked:
            expected = "protocol_violation"
        elif r["declared"] in incompatible:
            expected = "incompatible_config"
        elif not r.get("actions"):
            expected = "no_actions"
        elif r["actions"] <= 2:
            expected = "startup_only"
        elif r.get("reason") == "time" and (
                budget - window <= last_key_seconds(r, timeline_dir) <= budget or client_completed):
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
