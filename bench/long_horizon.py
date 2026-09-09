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
    "quests": 12,
}

# These are long-run gates.  The first seven mirror the existing benchmark's
# vocabulary for comparability; the last two are only long-horizon additions.
MILESTONES = (
    "acted",
    "picked_item",
    "world_map",
    "experience",
    "level_2",
    "companion",
    "book",
    "all_books",
    "ending",
)

# Long-horizon additions are deliberately separate from the short-run ladder.
# A checkpoint may use these stable English ids while its UI renders Chinese
# labels.  The short tier is a pointer to the frozen paper score, never a
# recomputation of it.
TIER_MILESTONES = {
    "short": ("acted", "picked_item", "world_map", "experience", "level_2",
               "companion", "book"),
    "medium": ("inn", "nanxian", "compass", "second_location"),
    "long": ("battle_won", "skill_gain", "book", "all_books", "ending"),
}


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


def _milestones(checkpoints: Sequence[Mapping]) -> tuple[set[str], bool]:
    reached, measured = set(), False
    valid = set(MILESTONES)
    valid.update(gate for gates in TIER_MILESTONES.values() for gate in gates)
    for checkpoint in checkpoints:
        if "milestones" not in checkpoint:
            continue
        measured = True
        values = checkpoint["milestones"]
        if isinstance(values, str):
            values = [values]
        if isinstance(values, Sequence):
            reached.update(v for v in values if v in valid)
    return reached, measured


def _component(points, value, measured, evidence):
    return {
        "points": round(points * value, 3) if measured else None,
        "maximum": points,
        "value": round(value, 6) if measured else None,
        "score": round(value * 100, 3) if measured else None,
        "measured": measured,
        "evidence": evidence,
    }


def _tier_report(reached, measured):
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
        known = [gate for gate in gates if gate in measured]
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
    ``milestones`` (a list from :data:`MILESTONES`), ``location``,
    ``quest_flags``, ``books`` (item ids), ``level``, ``team_size``,
    ``inventory_distinct``, ``recoveries`` and ``state_loss_events``.
    ``budget_seconds`` is metadata and never changes the frozen short score.
    """
    rows = _checkpoint_list(checkpoints)
    targets = {**DEFAULT_TARGETS, **(targets or {})}
    if any(_number(targets.get(k), integer=True) in (None, 0) for k in DEFAULT_TARGETS):
        raise ValueError("long-horizon targets must be positive integers")

    milestones, milestone_measured = _milestones(rows)
    # A milestone list is a complete read of the milestone instrument at that
    # checkpoint: omitted ids are known false, not silently unmeasured. Runs
    # that never provide the key keep every milestone unmeasured.
    all_measured_milestones = set()
    if any("milestones" in checkpoint for checkpoint in rows):
        all_measured_milestones = set(MILESTONES)
        all_measured_milestones.update(gate for gates in TIER_MILESTONES.values()
                                       for gate in gates)
    locations, location_measured = _union(rows, "locations")
    if not locations:
        locations, location_measured = _union(rows, "location")
    quests, quest_measured = _union(rows, "quest_flags")
    books, books_measured = _union(rows, "books")
    books = {book for book in books if book in BOOK_IDS}

    level, level_measured = _max_value(rows, "level")
    team, team_measured = _max_value(rows, "team_size")
    inventory, inventory_measured = _max_value(rows, "inventory_distinct")
    recoveries, recoveries_measured = _max_value(rows, "recoveries")
    losses, losses_measured = _max_value(rows, "state_loss_events")

    # The ordered-gate component gives credit for a journey that has not yet
    # reached a book.  It is separate from the frozen short-run score.
    prefix = 0
    for milestone in MILESTONES:
        if milestone not in milestones:
            break
        prefix += 1
    growth_values = (
        min(1.0, (level or 0) / 10) if level_measured else 0,
        min(1.0, (team or 0) / 6) if team_measured else 0,
        min(1.0, (inventory or 0) / 20) if inventory_measured else 0,
    )
    growth_measured = any((level_measured, team_measured, inventory_measured))
    components = {
        "milestone_progress": _component(
            30, prefix / len(MILESTONES), milestone_measured,
            {"reached": [m for m in MILESTONES if m in milestones],
             "next": MILESTONES[prefix] if prefix < len(MILESTONES) else None}),
        "exploration": _component(
            20, min(1.0, len(locations) / targets["locations"]),
            location_measured, {"unique_locations": len(locations), "target": targets["locations"]}),
        "growth": _component(
            20, sum(growth_values) / sum((level_measured, team_measured, inventory_measured))
            if growth_measured else 0,
            growth_measured,
            {"level": level, "team_size": team, "inventory_distinct": inventory}),
        "story": _component(
            15, min(1.0, len(quests) / targets["quests"]), quest_measured,
            {"unique_quest_flags": len(quests), "target": targets["quests"]}),
        "book_collection": _component(
            10, len(books) / len(BOOK_IDS), books_measured,
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
        "score": round(points / maximum * 100, 3) if maximum else None,
        "points": round(points, 3),
        "maximum_measured": maximum,
        "maximum_total": 100,
        "budget_seconds": _number(budget_seconds),
        "checkpoints": len(rows),
        "elapsed_seconds": rows[-1]["at"],
        "components": components,
        "tiers": _tier_report(milestones, all_measured_milestones),
        "short_metrics_unchanged": True,
    }
