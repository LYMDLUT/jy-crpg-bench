"""Additive long-horizon scoring for multi-hour game runs.

The published short-run metrics are deliberately not used here.  A harness
may submit a sequence of state checkpoints after a long run and receive a
secondary report describing the journey: ordered milestones, exploration,
growth, story coverage, book collection, and recovery.  Missing fields are
reported as unmeasured rather than treated as zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
BOOK_IDS = frozenset(range(144, 158))
DEFAULT_TARGETS = {
    "locations": 8,
    "story_nodes": 12,
}

# Stable evidence-backed route nodes.  A deployment may extend this registry,
# but a free-form string is never counted as a story node.
STORY_NODE_IDS = frozenset({
    "opening", "compass", "flying_fox", "snowy_fox", "liancheng",
    "tianlong", "shediao", "baima", "luding", "xiaoyao", "shujian",
    "shendiao", "xiake", "yitian", "bixue", "yuanyang",
})

HORIZON_BANDS = (
    ("short", 0, 20 * 60),
    ("medium", 30 * 60, 2 * 60 * 60),
    ("long", 24 * 60 * 60, 48 * 60 * 60),
)

SHORT_MILESTONES = (
    "acted", "picked_item", "world_map", "experience", "level_2",
    "companion", "book",
)

# Long-horizon additions are deliberately separate from the short-run ladder.
# A checkpoint may use these stable English ids while its UI renders Chinese
# labels.  The short tier is a pointer to the frozen paper score, never a
# recomputation of it.
TIER_MILESTONES = {
    "short": SHORT_MILESTONES,
    "medium": ("inn", "nanxian", "compass", "second_location"),
    "long": ("battle_won", "skill_gain", "book", "all_books", "ending"),
}

# These prerequisites express only hard, instrumentable dependencies from the
# walkthrough.  Optional route choices remain independent gates.
PREREQUISITES = {
    "nanxian": ("inn",),
    "compass": ("nanxian",),
    "all_books": ("book",),
    "ending": ("all_books",),
}


def _horizon(budget_seconds):
    budget = _number(budget_seconds)
    if budget is None:
        return None
    for name, low, high in HORIZON_BANDS:
        if low <= budget <= high:
            return name
    return "extended"


def _number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if integer and not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _checkpoint_list(checkpoints: Iterable[Mapping]) -> list[dict]:
    out = []
    previous = -1.0
    for raw in checkpoints:
        if not isinstance(raw, Mapping):
            raise ValueError("each checkpoint must be an object")
        at = _number(raw.get("at"))
        if at is None or at < previous:
            raise ValueError("checkpoint times must be non-negative and ordered")
        previous = float(at)
        out.append(dict(raw))
    if not out:
        raise ValueError("at least one checkpoint is required")
    return out


def _union(checkpoints: Sequence[Mapping], key: str) -> tuple[set, bool]:
    values, measured = set(), False
    for checkpoint in checkpoints:
        if key not in checkpoint or checkpoint[key] is None:
            continue
        measured = True
        value = checkpoint[key]
        if isinstance(value, str):
            values.add(value)
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            values.update(v for v in value if isinstance(v, (str, int)) and not isinstance(v, bool))
    return values, measured


def _max_value(checkpoints: Sequence[Mapping], key: str) -> tuple[float | None, bool]:
    values = [_number(c.get(key)) for c in checkpoints if key in c]
    values = [v for v in values if v is not None]
    return (max(values), True) if values else (None, False)


def _milestones(checkpoints: Sequence[Mapping]) -> tuple[set[str], bool, set[str]]:
    reached, measured = set(), False
    valid = set(gate for gates in TIER_MILESTONES.values() for gate in gates)
    measured_tiers = set()
    for checkpoint in checkpoints:
        if "milestones" not in checkpoint:
            continue
        measured = True
        tiers = checkpoint.get("measured_tiers", ["short"])
        if isinstance(tiers, str):
            tiers = [tiers]
        measured_tiers.update(tier for tier in tiers if tier in TIER_MILESTONES)
        values = checkpoint["milestones"]
        if isinstance(values, str):
            values = [values]
        if isinstance(values, Sequence):
            reached.update(v for v in values if v in valid)
    return reached, measured, measured_tiers


def _component(points, value, measured, evidence):
    return {
        "points": round(points * value, 3) if measured else None,
        "maximum": points,
        "value": round(value, 6) if measured else None,
        "score": round(value * 100, 3) if measured else None,
        "measured": measured,
        "evidence": evidence,
    }


def _tier_report(reached, measured, measured_tiers):
    """Report additive medium/long gates without touching short metrics."""
    reports = {}
    for tier, gates in TIER_MILESTONES.items():
        if tier == "short":
            reports[tier] = {
                "status": "frozen_external_metric",
                "score": None,
                "reached": [gate for gate in gates if gate in reached],
                "gates": list(gates),
                "measured": measured,
            }
            continue
        if tier not in measured_tiers:
            reports[tier] = {"status": "unmeasured", "score": None,
                             "reached": [], "gates": list(gates),
                             "measured_gates": []}
            continue
        known = list(gates)
        reached_known = [gate for gate in known if gate in reached]
        reports[tier] = {
            "status": "measured" if known else "unmeasured",
            "score": round(100 * len(reached_known) / len(known), 3) if known else None,
            "reached": reached_known,
            "gates": list(gates),
            "measured_gates": known,
        }
    return reports


def score_long_horizon(checkpoints: Iterable[Mapping], *, budget_seconds=None,
                       targets=None) -> dict:
    """Return an additive secondary score for a checkpoint trajectory.

    Checkpoints are harness-produced records.  Useful keys are ``at``,
    ``milestones`` (tier-specific gate ids), ``measured_tiers``, ``location``,
    ``story_nodes``, ``books`` (item ids), ``level``, ``team_size``,
    ``key_items``, ``recoveries`` and ``state_loss_events``.
    ``budget_seconds`` is metadata and never changes the frozen short score.
    """
    rows = _checkpoint_list(checkpoints)
    targets = {**DEFAULT_TARGETS, **(targets or {})}
    if any(_number(targets.get(k), integer=True) in (None, 0) for k in DEFAULT_TARGETS):
        raise ValueError("long-horizon targets must be positive integers")

    milestones, milestone_measured, measured_tiers = _milestones(rows)
    # A milestone list is a complete read of the milestone instrument at that
    # checkpoint: omitted ids are known false, not silently unmeasured. Runs
    # that never provide the key keep every milestone unmeasured.
    all_measured_milestones = set()
    if any("milestones" in checkpoint for checkpoint in rows):
        all_measured_milestones = set(gate for tier in measured_tiers
                                      for gate in TIER_MILESTONES[tier])
    locations, location_measured = _union(rows, "locations")
    if not locations:
        locations, location_measured = _union(rows, "location")
    story_nodes, story_measured = _union(rows, "story_nodes")
    story_nodes = {node for node in story_nodes if node in STORY_NODE_IDS}
    books, books_measured = _union(rows, "books")
    books = {book for book in books if book in BOOK_IDS}

    level, level_measured = _max_value(rows, "level")
    team, team_measured = _max_value(rows, "team_size")
    key_items, key_items_measured = _union(rows, "key_items")
    # Keep the old field readable for diagnostics, but do not award growth for
    # arbitrary inventory size. Key items are the guide's actual prerequisites.
    inventory, inventory_measured = _max_value(rows, "inventory_distinct")
    recoveries, recoveries_measured = _max_value(rows, "recoveries")
    losses, losses_measured = _max_value(rows, "state_loss_events")

    # Medium and long gates are scored as a dependency-aware set.  The frozen
    # short ladder is reported separately and is never recomputed here.
    long_gates = tuple(gate for tier in ("medium", "long")
                       if tier in measured_tiers for gate in TIER_MILESTONES[tier])
    valid_gates = list(dict.fromkeys(long_gates))
    valid_reached = {gate for gate in milestones if gate in valid_gates}
    for gate in list(valid_reached):
        if any(pre not in valid_reached for pre in PREREQUISITES.get(gate, ())):
            valid_reached.remove(gate)
    gate_fraction = len(valid_reached) / len(valid_gates) if valid_gates else 0
    components = {
        "milestone_progress": _component(
            25, gate_fraction, bool(valid_gates),
            {"reached": sorted(valid_reached), "measured_gates": valid_gates,
             "prerequisites": PREREQUISITES}),
        "exploration": _component(
            15, min(1.0, len(locations) / targets["locations"]),
            location_measured, {"unique_locations": len(locations), "target": targets["locations"]}),
        "growth": _component(
            15, sum((min(1.0, (level or 0) / 10) if level_measured else 0,
                     min(1.0, (team or 0) / 6) if team_measured else 0,
                     min(1.0, len(key_items) / 8) if key_items_measured else 0))
            / sum((level_measured, team_measured, key_items_measured))
            if any((level_measured, team_measured, key_items_measured)) else 0,
            any((level_measured, team_measured, key_items_measured)),
            {"level": level, "team_size": team, "key_items": sorted(key_items),
             "inventory_distinct_diagnostic": inventory}),
        "story": _component(
            15, min(1.0, len(story_nodes) / targets["story_nodes"]), story_measured,
            {"unique_story_nodes": len(story_nodes), "target": targets["story_nodes"]}),
        "book_collection": _component(
            25, len(books) / len(BOOK_IDS), books_measured,
            {"books": sorted(books), "count": len(books), "total": len(BOOK_IDS)}),
    }

    reliability_measured = recoveries_measured and losses_measured
    if reliability_measured:
        total = (recoveries or 0) + (losses or 0)
        reliability = (recoveries or 0) / total if total else 1.0
    else:
        reliability = 0.0
    components["reliability"] = _component(
        5, reliability, reliability_measured,
        {"recoveries": recoveries, "state_loss_events": losses})

    measured = [c for c in components.values() if c["measured"]]
    maximum = sum(c["maximum"] for c in measured)
    points = sum(c["points"] for c in measured)
    return {
        "schema_version": SCHEMA_VERSION,
        "score": round(points, 3) if maximum else None,
        "points": round(points, 3),
        "maximum_measured": maximum,
        "maximum_total": 100,
        "coverage": round(maximum / 100, 6),
        "budget_seconds": _number(budget_seconds),
        "horizon": _horizon(budget_seconds),
        "checkpoints": len(rows),
        "elapsed_seconds": rows[-1]["at"],
        "components": components,
        "tiers": _tier_report(milestones, all_measured_milestones, measured_tiers),
        "short_metrics_unchanged": True,
    }
