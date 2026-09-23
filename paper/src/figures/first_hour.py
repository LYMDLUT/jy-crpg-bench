"""The first hour of the four-hour sessions of a model with no hour session.

    python figures/first_hour.py

A model that ran only at the four-hour budget enters the hour field through the
first 60 minutes of each of its sessions, so every row of Figure 3 is read over
the same hour of play. For each such session this writes an hour session with
the id `<session>-h1`: a catalogue row in catalog_snapshot_firsthour.json, the
keypress timeline cut at minute 60 in timelines/, and the replay readings cut
at minute 60 in replay_events.json. Only what is known at minute 60 is kept:
the crossing, the save and the replay panels by their time, and the character
record, whose end values equal its start values for these sessions. The bag,
the party and the screen-change ratio are known only at the end of the session
and are left out.
"""
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_scan  # noqa: E402

MODELS = ("claude-opus-5.5",)
HOUR = 3600
LONG = os.path.join(HERE, "catalog_snapshot_240min.json")
OUT = os.path.join(HERE, "catalog_snapshot_firsthour.json")
EVENTS = os.path.join(HERE, "replay_events.json")
ALIASES = json.load(open(os.path.join(HERE, "aliases.json"), encoding="utf-8"))
UNCHANGED = ("level", "exp", "skills", "hp", "maxhp", "books", "potential", "reputation")


def cut_replay(e, speed):
    """The replay readings of the first hour: panel hits, scenes and the
    recruitment up to minute 60, the score maxima over the frames before it."""
    last = HOUR / speed                      # video seconds of the first hour
    out = dict(e, video_seconds=min(e["video_seconds"], int(last)))
    for n in replay_scan.NAMES + ("obtained",):
        p = e[n]
        cands = [c for c in p["candidates"] if c[0] < last]
        hits = [s for s, v in cands if v > replay_scan.THRESH]
        out[n] = {"seconds": len(hits),
                  "max": max((v for _, v in cands), default=None),
                  "first_minute": round(hits[0] * speed / 60, 1) if hits else None,
                  "minutes": [round(s * speed / 60, 1) for s in hits],
                  "candidates": cands}
    entries = [x for x in e["scenes"]["entries"] if x["minute"] <= HOUR / 60]
    away = [x for x in entries if x["name"] != replay_scan.HOME]
    out["scenes"] = {"entries": entries, "distinct": len({x["name"] for x in away}),
                     "first_minute": min((x["minute"] for x in away), default=None)}
    rm = e.get("recruited_minute")
    out["recruited_minute"] = rm if rm is not None and rm <= HOUR / 60 else None
    black = e.get("first_black_second")
    if black is None or black >= last:
        out["first_black_second"] = None
        out["crossing_actions"] = None
    return out


def cut_row(r, tl):
    marks = [m for m in tl["marks"] if m["t"] * tl["speed"] <= HOUR]
    at = [m["t"] * tl["speed"] for m in marks]
    gaps = [b - a for a, b in zip(at, at[1:])]
    keys = {}
    for m in marks:
        for k, _ in m["keys"]:
            keys[k] = keys.get(k, 0) + 1
    exit_in = r.get("exit_secs") is not None and r["exit_secs"] <= HOUR
    saved = r.get("first_saved_at")
    saved_in = saved is not None and saved - r["started"] <= HOUR
    row = {"id": r["id"] + "-h1", "session": r["id"], "agent": r["agent"],
           "started": r["started"], "budget": HOUR, "played": HOUR, "reason": "time",
           "why": "the first 60 minutes of a %d-minute session" % (r["budget"] // 60),
           "actions": len(marks), "decision_calls": len(marks),
           "key_events": sum(keys.values()), "keys": keys, "distinct_keys": len(keys),
           "wait_calls": 0, "ttfa": round(at[0], 2) if at else None,
           "aps": round(len(marks) / HOUR, 3),
           "gap_p50": round(st.median(gaps), 2) if gaps else None,
           "gap_p95": round(sorted(gaps)[int(0.95 * (len(gaps) - 1))], 2) if gaps else None,
           "gap_max": round(max(gaps), 2) if gaps else None,
           "bigmap": exit_in, "exit_acts": r["exit_acts"] if exit_in else None,
           "exit_secs": r["exit_secs"] if exit_in else None,
           "meaningful": None, "reads": None, "curve": [],
           "valid": True, "complete": True, "error": None,
           "video_url": r.get("video_url"), "poster_url": r.get("poster_url")}
    if saved_in:
        row["first_saved_at"] = row["saved_at"] = saved
    for k in UNCHANGED:
        row[k] = r.get(k)
    if (r.get("level"), r.get("exp")) != (1, 0):
        sys.exit("%s: the character record changed during the session; its minute-60 value is unknown" % r["id"])
    return row, dict(tl, id=row["id"], marks=marks, seconds=HOUR / tl["speed"])


def main():
    events = json.load(open(EVENTS, encoding="utf-8"))
    rows = []
    for r in json.load(open(LONG, encoding="utf-8")):
        if ALIASES.get(r["agent"], r["agent"]) not in MODELS or not r.get("actions"):
            continue
        if r["played"] < HOUR:
            sys.exit("%s played less than an hour" % r["id"])
        tl = json.load(open(os.path.join(HERE, "timelines", r["id"] + ".json"), encoding="utf-8"))
        row, cut = cut_row(r, tl)
        rows.append(row)
        json.dump(cut, open(os.path.join(HERE, "timelines", row["id"] + ".json"), "w", encoding="utf-8"))
        events[row["id"]] = dict(cut_replay(events[r["id"]], tl["speed"]), agent=r["agent"])
        print(row["id"], row["agent"], "actions", row["actions"], "crossed", row["exit_secs"],
              {n: events[row["id"]][n]["first_minute"] for n in ("hermit", "compass", "battle", "defeat", "obtained")})
    json.dump(rows, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(events, open(EVENTS, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
