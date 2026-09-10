"""The field the paper is generated from, loaded one way by every generator.

`catalog_snapshot.json` is the published catalogue as fetched; `aliases.json`
maps the names two runs were created under to the model the operator later
said had played, and every generator lists them under the model. The declared
name is kept on the row as `declared`. Service probes are dropped. The default
budget is read from bench/broker.py, so the field is whatever ran at the
budget the service hands out.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "catalog_snapshot.json")
EARLIER = os.path.join(HERE, "catalog_snapshot_20min.json")
ALIASES = json.load(open(os.path.join(HERE, "aliases.json"), encoding="utf-8"))
_broker = open(os.path.join(HERE, "..", "..", "..", "bench", "broker.py"), encoding="utf-8").read()
DEFAULT_BUDGET = int(re.search(r'"QUNXIA_RUN_SECONDS", "(\d+)"', _broker).group(1))


def load_runs(path=SNAPSHOT):
    rows = []
    for r in json.load(open(path, encoding="utf-8")):
        if r["agent"].startswith("probe-"):
            continue
        r = dict(r)
        r["declared"] = r["agent"]
        r["agent"] = ALIASES.get(r["agent"], r["agent"])
        rows.append(r)
    return rows


def played(rows, budget=DEFAULT_BUDGET):
    return [r for r in rows if r["budget"] == budget and (r["actions"] or 0) > 0]


def is_random(agent):
    return agent.lower().startswith("random")


def random_rows(rows, budget=DEFAULT_BUDGET):
    """The random floor: at the default budget when it was run there, else
    every random run there is. The ratio is per action, so the budget only
    matters for the budget section, which says which it used."""
    at = [r for r in played(rows, budget) if is_random(r["agent"])]
    return at or [r for r in rows if is_random(r["agent"]) and (r["actions"] or 0) > 0]


def aliased(rows):
    """(declared, listed) pairs for the rows whose name was corrected."""
    return sorted({(r["declared"], r["agent"]) for r in rows if r["declared"] != r["agent"]})


DEFINITION = ("acted", "picked\nsomething up", "reached\nworld map",
              "holds the\ncompass", "recruited\na companion",
              "gained\nexperience", "reached\nlevel 2", "holds one\nof fourteen")
SHORT = ("acted", "item", "map", "compass", "party", "exp", "lv 2", "book")
OPENING = 5     # the first five close the opening without a fight


def rungs_of(row):
    """(reached | not reached | None for no reading) per rung, as the game
    records them. The world-map rung is the game's own account of the party on
    the overworld: a save the game wrote there, or the live reading of its
    world square changing, whichever the run carries. A run recorded before the
    benchmark read either field is credited only from the screen with a
    corroborating fade, a legacy path the paper does not report."""
    saved = "saved_at" in row or "world_map_at" in row
    known = [
        True,
        row.get("picked_item") is not None,
        True if saved else row.get("bigmap") is not None,
        row.get("compass") is not None,
        row.get("team_size") is not None,
        row.get("exp") is not None,
        row.get("level") is not None,
        row.get("books") is not None,
    ]
    got = [
        (row.get("key_events") if row.get("key_events") is not None
         else row["actions"]) > 0,
        bool(row.get("picked_item")),
        (row.get("saved_at") is not None
         or row.get("world_map_at") is not None) if saved
        else bool(row.get("bigmap")) and row.get("exit_secs") is not None,
        bool(row.get("compass")),
        (row.get("team_size") or 0) > 1,
        (row.get("exp") or 0) > 0,
        (row.get("level") or 0) > 1,
        (row.get("books") or 0) > 0,
    ]
    return [(g if k else None) for g, k in zip(got, known)]


def rungs_reached(row):
    return sum(1 for v in rungs_of(row) if v is True)
