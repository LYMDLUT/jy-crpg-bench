"""Cross-check draft claims against the catalogue, without trusting memory.

Run from paper/src:

    python3 check_consistency.py

Prints claim-vs-fact lines and exits nonzero if any claim contradicts the
run data it cites.
"""

import json
import os
import re
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(SRC, "figures", "catalog_snapshot.json")
MAIN = os.path.join(SRC, "main.tex")


sys.path.insert(0, os.path.join(SRC, "figures"))
import field


def load_rows():
    # every session on record: the paper credits a model with any rung any of
    # its sessions reached, so the checks run over all of them
    return field.load_runs(dedup=False)


def claim(name, condition, fact):
    flag = "OK   " if condition else "CONTRADICTS "
    print("%s %s: %s" % (flag, name, fact))
    return condition


def main():
    rows = load_rows()
    scored = field.played(rows)
    read = [r for r in scored if r.get("bigmap") is not None]
    main_tex = open(MAIN, encoding="utf-8").read()
    ok = True

    # every numeric claim about map latching must match the generated stats
    latched = sum(1 for r in scored if r.get("bigmap") is True)
    corrob = sum(1 for r in scored if r.get("bigmap") is True and r.get("exit_secs") is not None)
    ok &= claim("map latches",
               ("none clears any later rung" not in main_tex) or (latched == 0),
               "%d latched, %d corroborated" % (latched, corrob))

    # progression claims must not use totals that include unread sessions
    prog = sum(1 for r in read if (r.get("exp") or 0) > 0)
    # the prose reads the experience total through its macro, so a run that
    # gains experience changes the number and not a sentence
    uses_macro = "\\SexpSum" in main_tex
    ok &= claim("progression floor", uses_macro,
               "sessions with exp>0 = %d, macro used = %s" % (prog, uses_macro))

    # no hardcoded run ratios in prose (they must come from macros)
    stray = re.findall(r"\b0\.\d{3}\b", main_tex)
    ok &= claim("hardcoded ratios", len(stray) == 0, "matches: %s" % (sorted(set(stray)) if stray else "none"))

    # inputs referenced must exist on disk
    missing = []
    for i in re.findall(r"\\input\{([^}]*)\}", main_tex):
        path = i if i.endswith(".tex") else i + ".tex"
        if not os.path.exists(os.path.join(SRC, path)):
            missing.append(path)
    ok &= claim("inputs present", not missing, "%s" % (missing if missing else "none"))

    # citations referenced must resolve in refs.bib
    bib = open(os.path.join(SRC, "refs.bib"), encoding="utf-8").read()
    keys = {k for k in re.findall(r"@\w+\{([^,\s]+),", bib)}
    cited = set()
    for grp in re.findall(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]*)\}", main_tex):
        cited.update(x.strip() for x in grp.split(","))
    ghost = sorted(cited - keys)
    ok &= claim("citations resolve", not ghost, "missing: %s" % ghost)

    # Typed claims about named runs in Section 4, each tied to the phrase that
    # makes it, so a regenerated field that no longer supports a sentence fails
    # here instead of going out in print.
    flat = re.sub(r"\s+", " ", main_tex)
    models = [r for r in scored if not field.is_random(r["agent"])]
    active = [r for r in models if r["actions"] >= 30]
    randoms = field.random_rows(rows)
    rk = sum(round(r["meaningful"] * r["actions"]) for r in randoms)
    rn = sum(r["actions"] for r in randoms)
    floor = rk / rn if rn else None
    if "the first milestone a random walk does not reach" in flat:
        ok &= claim("random never on the map", bool(randoms) and not any(field.on_map(r) for r in randoms),
                    "%d random runs" % len(randoms))
    if "save succeeds during its hour" in flat:
        ok &= claim("random floor never saved", not any(r.get("saved_at") for r in randoms),
                    "%d random runs" % len(randoms))
    on_map = [r for r in scored if field.on_map(r)]
    if "reach the world map" in flat:
        saved_map = {r["agent"] for r in on_map
                     if r.get("saved_at") is not None or r.get("world_map_at") is not None or r.get("slot_saved") is True}
        ok &= claim("every model's world-map credit has a save behind it in some session",
                    {r["agent"] for r in on_map} <= saved_map,
                    "%d sessions on the map, %d models save-backed" % (len(on_map), len(saved_map)))
    holders = [r for r in models if r.get("compass")]
    if "every milestone any of its sessions reached" in flat:
        union = {m["agent"]: m for m in field.model_rows(models)}
        ok &= claim("a model's rung is the union over its sessions",
                    all(union[a]["rungs"][k] is (True if any(field.rungs_of(r)[k] is True for r in models if r["agent"] == a) else union[a]["rungs"][k])
                        for a in union for k in range(len(field.DEFINITION))),
                    "%d models, %d sessions" % (len(union), len(models)))
        H, C, F, D = (field.DEFINITION.index(x) for x in ("spoke with\nthe hermit", "holds the\ncompass", "entered\na fight", "fought to\nthe end"))
        ok &= claim("the compass is never held without the hermit's conversation",
                    all(m["rungs"][H] for m in union.values() if m["rungs"][C]),
                    "compass %s" % [a for a, m in union.items() if m["rungs"][C]])
        ok &= claim("a fight fought to the end was entered",
                    all(m["rungs"][F] for m in union.values() if m["rungs"][D]),
                    "fought out %s" % [a for a, m in union.items() if m["rungs"][D]])
    if "plays past the opening of the game" in flat:
        FIGHT = field.DEFINITION.index("entered\na fight")
        past = [m["agent"] for m in field.model_rows(models) if m["rungs"][FIGHT] is True]
        ok &= claim("one model plays past the opening", len(past) == 1, "past the opening: %s" % past)
    if "the fingerprint never appears without a save behind it" in flat:
        ok &= claim("no screen latch without a save",
                    not any(r.get("bigmap") is True and not field.on_map(r) for r in scored),
                    "%d screen latches" % sum(1 for r in scored if r.get("bigmap") is True))
    if "crossing the fingerprint missed" in flat:
        ok &= claim("save-only crossing exists",
                    any(field.on_map(r) and r.get("bigmap") is False for r in scored),
                    "%d save-only crossings" % sum(1 for r in scored if field.on_map(r) and r.get("bigmap") is False))
        # the reliability sentences of Section 4.2 are recomputed here from every
    # session and compared with the macros the prose reads
    nums = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}",
                           open(os.path.join(SRC, "figures", "numbers.tex"), encoding="utf-8").read()))
    by_model = {}
    for r in models:
        by_model.setdefault(r["agent"], []).append(r)
    if "cross in every session they played" in flat:
        every = sorted(a for a, rs in by_model.items() if all(field.on_map(r) for r in rs))
        crossed = sum(1 for r in models if field.on_map(r))
        ok &= claim("sessions crossed and models crossing every time match the macros",
                    (int(nums["LcrossSessions"]), int(nums["LcrossEvery"])) == (crossed, len(every)),
                    "%d of %d sessions crossed, every time: %s" % (crossed, len(models), every))
    if "reached him in every one of its" in flat:
        H = field.DEFINITION.index("spoke with\nthe hermit")
        FIGHT = field.DEFINITION.index("entered\na fight")
        top = [m["agent"] for m in field.model_rows(models) if m["rungs"][FIGHT] is True]
        hermit = {a: sum(1 for r in rs if field.rungs_of(r)[H] is True) for a, rs in by_model.items()}
        others = {a: n for a, n in hermit.items() if n and a not in top}
        ok &= claim("the top model reached the hermit in every session, the others in the stated share",
                    len(top) == 1 and hermit[top[0]] == len(by_model[top[0]])
                    and (int(nums["LhermitOthers"]), int(nums["LhermitOthersMax"])) == (len(others), max(others.values()))
                    and all(len(by_model[a]) == int(nums["LhermitOthersPlayed"]) for a in others),
                    "top %s %s, others %s" % (top, {a: (hermit[a], len(by_model[a])) for a in top}, {a: (n, len(by_model[a])) for a, n in others.items()}))
    if "agrees with the count the service recorded" in flat:
        both = [r for r in models if r.get("exit_acts") is not None and (r.get("replay") or {}).get("crossing_actions") is not None]
        ok &= claim("replay and service crossing counts agree on every session carrying both",
                    bool(both) and len(both) == int(nums["LcrossAgree"])
                    and all(r["exit_acts"] == r["replay"]["crossing_actions"] for r in both),
                    "%d sessions carry both" % len(both))
    if "share of sessions in which the model reached the milestone" in flat:
        union = {m["agent"]: m for m in field.model_rows(models)}
        ok &= claim("every marker share is read from every session and agrees with the credit",
                    all(c[1] == c[2] for m in union.values() for c in m["counts"])
                    and all((m["rungs"][k] is True) == (m["counts"][k][0] > 0)
                            for m in union.values() for k in range(len(field.DEFINITION))),
                    "%d models, %d cells" % (len(union), sum(len(m["counts"]) for m in union.values())))
    if "across the sessions that crossed" in flat:
        union = field.model_rows(models)
        ok &= claim("each box plot holds one count per session that crossed",
                    all(len(m["crossings"]) == sum(1 for r in by_model[m["agent"]] if field.on_map(r))
                        and m["crossings"] == sorted(a for a in (field.crossing_actions(r) for r in by_model[m["agent"]]) if a is not None)
                        for m in union),
                    "%s" % {m["agent"]: len(m["crossings"]) for m in union})
    if "sessions with no bag reading" in flat:
        both = [r for r in scored if r.get("picked_item") is not None and (r.get("replay") or {}).get("obtained")]
        only = [r for r in scored if r.get("picked_item") is None and (r.get("replay") or {}).get("obtained")]
        ok &= claim("the obtained message agrees with every bag reading and covers the rest",
                    bool(both) and all(bool(r["picked_item"]) == (r["replay"]["obtained"]["seconds"] > 0) for r in both)
                    and not any(r.get("picked_item") is None and not (r.get("replay") or {}).get("obtained") for r in scored)
                    and (int(nums["PobtainedAgree"]), int(nums["PobtainedRead"])) == (len(both), len(only)),
                    "%d with both, %d from the message alone" % (len(both), len(only)))
    def seen(r, n):
        e = r.get("replay") or {}
        return bool(e.get(n) and e[n]["seconds"] > 0)
    if "shows the coordinate line on the replay, and no other session does" in flat:
        cb = [r for r in scored if r.get("replay") and r.get("compass") is not None]
        ok &= claim("the compass panel and the bag agree in both directions",
                    bool(cb) and all(seen(r, "compass") == bool(r["compass"]) for r in cb)
                    and (int(nums["PcompassBoth"]), int(nums["PcompassBag"])) == (len(cb), sum(1 for r in cb if r["compass"])),
                    "%d sessions with both, %d with the compass" % (len(cb), sum(1 for r in cb if r["compass"])))
    if "also shows his portrait on the replay" in flat:
        hb = [r for r in scored if r.get("replay") and r.get("world_opened") is not None]
        ok &= claim("every save with the hermit's scenes opened has his portrait on the replay",
                    bool(hb) and not any(r["world_opened"] and not seen(r, "hermit") for r in hb)
                    and (int(nums["PhermitBoth"]), int(nums["PhermitOpened"])) == (len(hb), sum(1 for r in hb if r["world_opened"])),
                    "%d sessions with both, %d opened" % (len(hb), sum(1 for r in hb if r["world_opened"])))
    if "any threshold between the two gives the same readings" in flat:
        panels = ("hermit", "compass", "battle", "defeat", "prompt", "obtained")
        ev = [r["replay"] for r in scored if r.get("replay")]
        miss = max(e[n]["max"] for e in ev for n in panels if e[n]["seconds"] == 0 and e[n]["max"] is not None)
        hit = min(e[n]["max"] for e in ev for n in panels if e[n]["seconds"] > 0)
        ok &= claim("the replay threshold sits between the highest miss and the lowest hit",
                    miss < float(nums["ReplayThreshold"]) <= hit and abs(float(nums["ReplayMissMax"]) - miss) < 0.006 and abs(float(nums["ReplayHitMin"]) - hit) < 0.006,
                    "miss %.3f, threshold %s, hit %.3f" % (miss, nums["ReplayThreshold"], hit))
    if "models entered a scene" in flat:
        SCENE = field.DEFINITION.index("entered\na scene")
        union = field.model_rows(models)
        entered = [m["agent"] for m in union if m["rungs"][SCENE] is True]
        ok &= claim("the scene milestone is read for every session and the count matches the macro",
                    all(c[1] == c[2] for m in union for c in [m["counts"][SCENE]])
                    and (int(nums["Lscene"]), int(nums["LnoScene"])) == (len(entered), len(union) - len(entered)),
                    "%d models entered a scene: %s" % (len(entered), entered))
    if "neither the fastest between actions nor the one that took the most actions" in flat:
        # Section 4: the pace did not set the order. The medians are the ones
        # tables/effort.tex prints, over every session of the model.
        import statistics as st
        top = max(field.model_rows(models), key=lambda m: (m["reached"], m["agent"]))["agent"]
        acts = {a: st.median([r["actions"] for r in rs]) for a, rs in by_model.items()}
        gaps = {a: st.median([r["gap_p50"] for r in rs]) for a, rs in by_model.items()
                if all(r.get("gap_p50") is not None for r in rs)}
        busiest = max(acts, key=acts.get)
        fastest = min(gaps, key=gaps.get) if len(gaps) == len(by_model) else None
        ok &= claim("the top model is neither the fastest between actions nor the busiest",
                    fastest is not None and top not in (busiest, fastest),
                    "top %s, most actions %s, fastest %s" % (top, busiest, fastest))

    # Validate the provisional submissions unconditionally, not by prose keywords.
    import long_cohort
    attempts = field.long_attempts()
    manifest = long_cohort.validate(attempts)
    long_rows = field.load_long()
    selected_ids = {r["id"] for r in long_rows}
    table = open(os.path.join(SRC, "tables/long.tex"), encoding="utf-8").read()
    table_ids = set(re.findall(r"[0-9a-f]{12}", table))
    ok &= claim("curated table exactly matches the manifest", table_ids == selected_ids, str(sorted(table_ids)))
    ok &= claim("one provisional submission per model", len(long_rows) == len({r["agent"] for r in long_rows}), str(len(long_rows)))
    ok &= claim("attempt and submission counts match generated macros",
                (int(nums["NlongAttempts"]), int(nums["NlongSessions"]), int(nums["NlongWithheld"]))
                == (len(attempts), len(long_rows), len(attempts) - len(long_rows)), str(len(attempts)))
    ok &= claim("documented protocol violation is not credited", field.HACK_SESSION not in selected_ids, field.HACK_SESSION)
    for rung in ("holds the\ncompass", "entered\na fight", "gained\nexperience", "one of the\nfourteen"):
        k = field.DEFINITION.index(rung)
        ok &= claim("selected submissions have no " + rung.replace("\n", " "),
                    not any(field.rungs_of(r)[k] is True for r in long_rows), str(len(long_rows)))
    if "sessions before the hour" in flat:
        idle = sum(1 for r in models if r.get("reason") == "idle")
        ok &= claim("the idle-ended session count matches the macro", idle > 0 and int(nums["NidleSessions"]) == idle,
                    "%d idle-ended" % idle)
    if "loses the fight fought to its end, and no other count changes" in flat:
        full = {m["agent"]: m for m in field.model_rows(models)}
        without = {m["agent"]: m for m in field.model_rows([r for r in models if r.get("reason") != "idle"])}
        FOUGHT = field.DEFINITION.index("fought to\nthe end")
        diff = {a: full[a]["reached"] - without[a]["reached"] for a in full if a in without and full[a]["reached"] != without[a]["reached"]}
        top = nums["LtopLabel"].replace("\\texttt{", "").rstrip("}")
        ok &= claim("excluding the idle-ended sessions lowers one count by one, the fight fought to its end",
                    diff == {top: 1} and full[top]["rungs"][FOUGHT] is True and without[top]["rungs"][FOUGHT] is not True
                    and all(a in without for a in full),
                    "%s" % diff)
    # The human references of Figure 3, read from human_sessions.json.
    if "cross onto the world map within the first minute" in flat:
        speed = [v for v in field.human_videos() if v["class"] == "speedrun"]
        ok &= claim("every speedrun crosses within the first minute",
                    bool(speed) and all(v["milestones_min"]["map"] is not None and v["milestones_min"]["map"] < 1 for v in speed),
                    "%s" % [v["milestones_min"]["map"] for v in speed])
    if "human references read from published videos" in flat:
        vids = field.human_videos()
        ok &= claim("every human video carries a reading for every milestone and its steps",
                    bool(vids) and all(set(v["milestones_min"]) == set(field.HUMAN_KEYS) and v.get("steps_to_map") is not None for v in vids),
                    "%d videos" % len(vids))
    if "all of which finish the game" in flat:
        speed = [v for v in field.human_videos() if v["class"] == "speedrun"]
        ok &= claim("every speedrun finishes the game",
                    bool(speed) and all(v.get("completion_min") is not None for v in speed),
                    "%s" % [v.get("completion_min") for v in speed])
    if "one of which reaches the ending" in flat:
        plays = [v for v in field.human_videos() if v["class"] == "playthrough"]
        ok &= claim("exactly one playthrough reaches the ending",
                    sum(1 for v in plays if v.get("completion_min") is not None) == 1,
                    "%s" % [v.get("completion_min") for v in plays])
    if "in which a human speedrun finishes the game" in flat:
        speed = [v for v in field.human_videos() if v["class"] == "speedrun"]
        ok &= claim("a speedrun finishes the game within the hour budget",
                    any(v.get("completion_min") is not None and v["completion_min"] <= field.DEFAULT_BUDGET / 60 for v in speed),
                    "%s" % [v.get("completion_min") for v in speed])

    print("\n%d runs scored, %d sessions with a map verdict, %d maps latched"
          % (len(scored), len(read), latched))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
