"""Self-terminating benchmark run.

One game server process is one benchmark run. The process that played the game
is the one that decides the run is over, renders it, publishes it, and exits -
nothing outside has to watch a clock on its behalf. That keeps teardown local
to whichever node happens to be running the session, so the fleet scales by
adding nodes rather than by making one supervisor bigger.

Off unless QUNXIA_BENCH is set, so the interactive server is unaffected.
"""
import asyncio
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "bench"))

ON = os.environ.get("QUNXIA_BENCH") == "1"
AGENT = os.environ.get("QUNXIA_BENCH_AGENT", "agent")
SID = os.environ.get("QUNXIA_BENCH_SID", "")
BUDGET = int(os.environ.get("QUNXIA_BENCH_BUDGET", "1200"))
IDLE = int(os.environ.get("QUNXIA_BENCH_IDLE", "600"))
BUCKET = os.environ.get("QUNXIA_GCS_BUCKET", "")
RESULTS = pathlib.Path(os.environ.get("QUNXIA_RESULT_DIR", "/tmp/qunxia-results"))
VIDEOS = pathlib.Path(os.environ.get("QUNXIA_VIDEO_DIR", "/tmp/qunxia-videos"))
# Where this backend serves its own files from, used only when there is no
# bucket, ie local development. Distinct from SITE, which is the published
# catalogue and is not this service at all.
PUBLIC_BASE = os.environ.get("QUNXIA_PUBLIC_BASE", "").rstrip("/")
SITE = os.environ.get("QUNXIA_BENCH_SITE", "https://hanxiao.io/jy-crpg-bench/")
CATALOG_OBJECT = "catalog.json"

# Filled in by the server as the agent plays. Kept here rather than in the
# proxy so the numbers survive however the run is fronted.
run = {"playable": None, "first": None, "last": None, "gaps": [], "keys": {},
       "reads": 0, "errors": 0, "actions": 0, "places": 0,
       "meaningful": 0, "oscillation": 0, "dialogue": 0, "curve": [],
       "done": None, "result": None}


def playable_now():
    """Called once the savestate is in and the agent may act."""
    run["playable"] = time.time()


def note_action(keys, label=""):
    now = time.time()
    if run["last"] is not None:
        run["gaps"].append(now - run["last"])
    else:
        run["first"] = now
    run["last"] = now
    run["actions"] += 1
    for k in keys or []:
        run["keys"][k] = run["keys"].get(k, 0) + 1


def note_read():
    run["reads"] += 1


def ended_payload():
    """What an agent gets once its run is over. Present as soon as the run is
    called, so a late request is answered even while the video renders."""
    if not run["done"]:
        return None
    res = run["result"] or {}
    return {"ok": True, "ended": True,
            "message": "This benchmark run has ended. Stop playing.",
            "agent": AGENT, "reason": run["done"], "why": why_text(),
            "actions": run["actions"],
            "played_seconds": round((run["last"] or run["playable"] or 0)
                                    - (run["playable"] or 0)),
            "video_url": res.get("video_url"),
            "video_pending": res.get("video_url") is None,
            "catalog_url": SITE}


def human(sec):
    sec = int(sec or 0)
    if sec < 120:
        return f"{sec} seconds"
    m, s = divmod(sec, 60)
    return f"{m} {'minute' if m == 1 else 'minutes'}" + (f" {s}s" if s else "")


def why_text():
    if run["done"] == "time":
        return f"the full {human(BUDGET)} budget was used"
    idle = human(time.time() - (run["last"] or run["playable"] or time.time()))
    if run["done"] == "never started":
        return f"no action was ever sent - the run sat unplayed for {idle}"
    return (f"no action arrived for {idle}, so the run was stopped early. "
            f"Spending that long on one step is a failure, not thinking")


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def metrics():
    playable = run["playable"] or time.time()
    played = max(0.0, (run["last"] or playable) - playable)
    n, gaps = run["actions"], run["gaps"]
    return {
        "id": SID, "agent": AGENT, "started": playable,
        "played": round(played), "budget": BUDGET,
        "actions": n, "reason": run["done"] or "time",
        "ttfa": round(run["first"] - playable, 2) if run["first"] else None,
        "aps": round(n / played, 3) if played > 0.5 and n else 0.0,
        "gap_p50": pct(gaps, 0.5), "gap_p95": pct(gaps, 0.95),
        "gap_max": round(max(gaps), 2) if gaps else None,
        "reads": run["reads"], "errors": run["errors"],
        # Distinct places stood in, and how much of the agent's effort turned
        # into new ground rather than retracing.
        "places": run["places"],
        "reach": round(run["places"] / n, 3) if n else 0.0,
        # Meaningful step ratio, GVGAI-LLM arXiv:2508.08501: the share of
        # actions that changed the state at all.
        "meaningful": round(run["meaningful"] / n, 3) if n else 0.0,
        # Repetition rate, AgentQuest arXiv:2404.06411, adapted to a spatial
        # game: actions that did not reach new ground, over actions taken.
        "repetition": round(1 - run["places"] / n, 3) if n else 0.0,
        # A -> B -> A oscillation, the failure mode GVGAI-LLM names explicitly.
        "oscillation": round(run["oscillation"] / n, 3) if n else 0.0,
        "dialogue": run["dialogue"],
        # Progress against step count, the shape TextQuests and BALROG plot.
        "curve": run["curve"][-200:],
        "keys": dict(sorted(run["keys"].items(), key=lambda kv: -kv[1])),
        "distinct_keys": len(run["keys"]),
    }


# ------------------------------------------------------------------ publish

def _bucket():
    if not BUCKET:
        return None
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def publish(path: pathlib.Path):
    b = _bucket()
    if b is None:
        return f"{PUBLIC_BASE}/videos/{path.name}" if PUBLIC_BASE else None
    blob = b.blob(path.name)
    blob.upload_from_filename(str(path), content_type="video/mp4")
    blob.cache_control = "public, max-age=31536000, immutable"
    blob.patch()
    return f"https://storage.googleapis.com/{BUCKET}/{path.name}"


def publish_bytes(name, data, mime, max_age=31536000):
    b = _bucket()
    if b is None:
        out = pathlib.Path(os.environ.get("QUNXIA_LOCAL_PUBLIC",
                                          "/tmp/qunxia-public")) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return
    blob = b.blob(name)
    blob.cache_control = f"public, max-age={max_age}"
    blob.upload_from_string(data, content_type=mime)


def append_catalog(entry):
    """Nodes finish independently, so the shared list is written with a
    generation precondition and retried rather than last-write-wins."""
    b = _bucket()
    if b is None:
        local = pathlib.Path(os.environ.get("QUNXIA_CATALOG",
                                            "/tmp/qunxia-catalog.json"))
        runs = json.loads(local.read_text()) if local.exists() else []
        local.write_text(json.dumps([entry] + runs, indent=1))
        return
    from google.api_core.exceptions import PreconditionFailed
    for attempt in range(12):
        # get_blob fetches the metadata, so generation is a real number.
        # b.blob() alone leaves it None, which omits the precondition entirely
        # and quietly turns concurrent appends into last-write-wins.
        blob = b.get_blob(CATALOG_OBJECT)
        if blob is None:
            blob, runs, gen = b.blob(CATALOG_OBJECT), [], 0
        else:
            gen = blob.generation
            try:
                runs = json.loads(blob.download_as_bytes())
            except Exception:
                runs = []
        runs = [entry] + [r for r in runs if r.get("id") != entry["id"]]
        try:
            blob.upload_from_string(json.dumps(runs[:500]),
                                    content_type="application/json",
                                    if_generation_match=gen)
            blob.cache_control = "public, max-age=15"
            blob.patch()
            return
        except PreconditionFailed:
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("catalogue is too contended to append to")


def write_result(res):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{SID}.json").write_text(json.dumps(res))


# ------------------------------------------------------------------ the loop

async def warden(rec):
    """Ends the run on whichever comes first - the clock or a long silence -
    then publishes it and takes the process down with it."""
    while run["playable"] is None:
        await asyncio.sleep(1)
    deadline = run["playable"] + BUDGET
    while True:
        now = time.time()
        if now >= deadline:
            run["done"] = "time"
            break
        if now - (run["last"] or run["playable"]) >= IDLE:
            run["done"] = "idle" if run["last"] else "never started"
            break
        await asyncio.sleep(min(5, max(1, deadline - now)))

    res = dict(metrics(), why=why_text(), video_url=None, error=None)
    run["result"] = res
    write_result(res)                      # answer late callers straight away
    try:
        from render import render
        VIDEOS.mkdir(parents=True, exist_ok=True)
        out = VIDEOS / f"{AGENT}-{SID}.mp4"
        loop = asyncio.get_running_loop()
        # The pump keeps appending frames after the run is called, so hand the
        # renderer its own list rather than one being written underneath it.
        snap = dict(rec, events=list(rec["events"]))
        info = await loop.run_in_executor(None, lambda: render(snap, out, AGENT))
        timeline = info.pop("timeline", None)
        res["video"] = {k: v for k, v in info.items() if k != "path"}
        res["video_url"] = await loop.run_in_executor(None, publish, out)
        # The scrubbable replay: a few KB describing what happened when, so the
        # page can drive the MP4 rather than ship the whole recording.
        if timeline is not None:
            timeline.update(agent=AGENT, id=SID, curve=run["curve"][-400:],
                            keys=dict(sorted(run["keys"].items(),
                                             key=lambda kv: -kv[1])))
            await loop.run_in_executor(
                None, publish_bytes, f"runs/{SID}.json",
                json.dumps(timeline).encode(), "application/json")
            res["timeline_url"] = f"runs/{SID}.json"
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
    try:
        await asyncio.get_running_loop().run_in_executor(None, append_catalog, res)
    except Exception as exc:
        res["error"] = (res["error"] or "") + f" catalogue: {exc}"
    write_result(res)
    print(f"bench run {SID} finished: {res['reason']} "
          f"{res['actions']} actions -> {res.get('video_url')}", flush=True)
    await asyncio.sleep(1)                 # let the last reply flush
    os._exit(0)
