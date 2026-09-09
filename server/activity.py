"""Bounded, atomic activity snapshots for an opt-in, single-owner session."""
import json
import math
import os
from pathlib import Path
import tempfile

MAX_ENTRIES = 300
MAX_BYTES = 4 * 1024 * 1024
MAX_THUMB = 64 * 1024


def clean_entries(entries):
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError("invalid activity history length")
    result = []
    last_id = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid activity entry")
        seq, at = entry.get("id"), entry.get("at")
        if type(seq) is not int or seq <= last_id:
            raise ValueError("invalid activity sequence")
        if type(at) not in (int, float) or not math.isfinite(at):
            raise ValueError("invalid activity timestamp")
        row = {"id": seq, "at": at, "ok": entry.get("ok") is True}
        for key in ("src", "verb", "target", "detail"):
            value = entry.get(key, "")
            if not isinstance(value, str):
                raise ValueError("invalid activity text")
            row[key] = value[:256]
        thumb = entry.get("thumb")
        if isinstance(thumb, str) and len(thumb) <= MAX_THUMB and thumb.startswith("data:image/webp;base64,"):
            row["thumb"] = thumb
        result.append(row)
        last_id = seq
    # Match the live panel's thumbnail budget.
    thumbs = [row for row in result if "thumb" in row]
    for row in thumbs[:-40]:
        row.pop("thumb")
    return result


class ActivityStore:
    """Keep the last 300 entries, independent of benchmark/session counters.

    The caller owns this path exclusively (one save directory per server).
    A failed write leaves the previous complete snapshot intact.
    """
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return []
        if len(raw) > MAX_BYTES:
            raise ValueError("activity snapshot exceeds size limit")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("unsupported activity snapshot")
        return clean_entries(data.get("entries"))

    def save(self, entries):
        rows = clean_entries(list(entries)[-MAX_ENTRIES:])
        raw = json.dumps({"version": 1, "entries": rows}, ensure_ascii=True).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("activity snapshot exceeds size limit")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".activity-", delete=False) as stream:
                name = stream.name
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)
