# Long-horizon scoring

This is an additive secondary report for runs that last longer than the
paper's short benchmark. It does not change the existing short-run fields,
the published 20-minute results, their confidence intervals, or the current
leaderboard ordering.

## Why a second report exists

The current benchmark answers an intentionally narrow question: can an agent
make useful progress during a short, fixed wall-clock window? That result is
already reported in the paper and must remain comparable. A ten-hour run
answers a different question. It may not hold a book yet, but it can still
show whether the agent discovered the overworld, found the inn, reached Nan
Xian, obtained the compass, recruited a companion, won a battle, learned a
skill, and preserved state across a long sequence. Collapsing that trajectory
to the unchanged short score would discard useful evidence.

The long-horizon report therefore publishes a trajectory and a secondary
score. It never replaces a short score and never turns an unmeasured field into
a failure.

## Three horizons

| Horizon | Wall-clock budget | What it asks | Examples of evidence |
| --- | ---: | --- | --- |
| Short | 20 minutes | Can the agent operate and make early progress? | Existing paper metrics: acted, picked something up, reached the world map, experience, level, companion, and book fields |
| Medium | 30 minutes to 2 hours | Can it establish a plan and carry dependencies across several locations? | Inn, Nan Xian, compass, a second meaningful location, first battle, companion, skill or story nodes |
| Long | 24 to 48 hours | Can it sustain a coherent route through the game's story? | Repeated battles, durable growth, multiple story chains, books held with evidence, all fourteen books, ending state |

The medium horizon has two natural checkpoints. **M1** is the opening route:
leave the home, reach the inn, find Nan Xian and obtain the compass. **M2** is
the first multi-location plan: reach another meaningful location, complete a
battle or training step, and keep the resulting state after a save/load
checkpoint. A run can pass M1 without passing M2.

The long horizon is deliberately not “fourteen books or zero”. Book count is
one component of the long report. A long run with no book can still receive
measured journey evidence for exploration, growth, story flags and battles;
the book component remains zero only when the harness measured that no book was
held. If books were never instrumented, that component is unmeasured.

## Checkpoint contract

The scorer accepts an ordered JSON array of checkpoints. A checkpoint has an
elapsed `at` time and may contain the following fields:

```json
{
  "at": 7200,
  "measured_tiers": ["medium", "long"],
  "milestones": ["inn", "nanxian", "compass", "battle_won"],
  "locations": ["home", "inn", "nanxian", "kunlun"],
  "story_nodes": ["opening", "tianlong"],
  "books": [],
  "level": 4,
  "team_size": 3,
  "key_items": ["compass", "jade_seal"],
  "inventory_distinct": 14,
  "recoveries": 1,
  "state_loss_events": 0
}
```

`measured_tiers` is required for medium and long scoring. If omitted, a
`milestones` list is treated as short-tier data only. This prevents an old
short run from being interpreted as a measured long-run failure.

`milestones` uses these stable ids:

- Medium: `inn`, `nanxian`, `compass`, `second_location`.
- Long: `battle_won`, `skill_gain`, `book`, `all_books`, `ending`.

The existing short ids may also be present for cross-referencing, but the
short score remains owned by the existing scorer: `acted`, `picked_item`,
`world_map`, `experience`, `level_2`, `companion`, and `book`.

`story_nodes` is restricted to the registered book and opening nodes. Unknown
free-form strings are ignored. A location should be emitted only after an
entry, coordinate checkpoint, or reliable dialogue/event record. A book should
be emitted from the game's item or story state and not from a model's text.
The scorer treats checkpoint times as ordered and rejects a backwards clock.

## Secondary score

The optional long report has 100 maximum points. Its components are kept
separate in the JSON so a reader can see why a run scored as it did:

| Component | Points | Measurement |
| --- | ---: | --- |
| Medium/long gate progression | 25 | Dependency-aware gates; the frozen short ladder is reported separately |
| Exploration | 15 | Unique evidence-backed locations against a configurable target (default 8) |
| Growth | 15 | The best observed level, team size, and key-item set; arbitrary inventory size is diagnostic only |
| Story coverage | 15 | Unique registered story nodes against a configurable target (default 12) |
| Book collection | 25 | Verified book ids out of 14 |
| Reliability | 5 | Recovery events divided by recovery plus state-loss events, when both are measured |

The displayed `score` uses a fixed 100-point denominator. The report also
returns `maximum_measured` and `coverage`; a run with only a partial instrument
cannot receive a falsely high normalized score. Missing components remain
explicit and should not be compared across runs with different coverage. The
`short_metrics_unchanged` marker makes the separation machine-checkable.

This weighting is a secondary analysis convention, not a new claim about the
paper's short benchmark. For scientific comparisons, publish the component
vector, checkpoint timeline, budget, and evidence source beside the aggregate;
do not rank two runs solely by the aggregate when their measured coverage
differs.

## What is intentionally unchanged

The existing short fields (`meaningful`, `oscillation`, `reads`, `ttfa`,
`actions`, the current milestone fields, and the paper tables) remain byte and
schema compatible. No old run is re-scored. No long-run field is fed back into
the 20-minute confidence intervals. A future long-run leaderboard can show the
secondary report beside the short score, but it must label the horizons and
budgets separately.
