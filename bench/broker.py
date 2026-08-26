#!/usr/bin/env python3
"""Benchmark broker.

One game per agent, isolated in its own process, time limited. When the clock
runs out the session is finalised without anyone watching: the recording is
rendered to MP4, uploaded, and listed in the catalogue. The agent learns the
run is over from its next call.
"""
import asyncio
import json
import os
import pathlib
import shutil
import socket
import subprocess
import time
import uuid

import aiohttp
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
SERVER = REPO / "server" / "server.py"
PYTHON = os.environ.get("QUNXIA_PYTHON", str(REPO / ".venv" / "bin" / "python"))
VIDEO_DIR = pathlib.Path(os.environ.get("QUNXIA_VIDEO_DIR", "/tmp/qunxia-videos"))
CATALOG_FILE = pathlib.Path(os.environ.get("QUNXIA_CATALOG", "/tmp/qunxia-catalog.json"))
GCS_BUCKET = os.environ.get("QUNXIA_GCS_BUCKET", "")
PUBLIC_BASE = os.environ.get("QUNXIA_PUBLIC_BASE", "")
RUN_SECONDS = int(os.environ.get("QUNXIA_RUN_SECONDS", "1200"))     # 20 minutes
# An agent that has not acted in this long is wedged, not thinking. Runs are
# scored on what they do with the clock, so a stalled one is torn down and told
# why rather than holding a machine until the full clock expires.
IDLE_LIMIT = int(os.environ.get("QUNXIA_IDLE_LIMIT", "600"))       # 10 minutes
BOOT_TIMEOUT = 90

# Endpoints that count as the agent taking a turn. Reading the screen keeps a
# session alive in the HTTP sense but is not an action.
ACTION_PATHS = ("api/key", "api/keys", "api/wait")

sessions: dict[str, dict] = {}
catalog: list[dict] = []


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


CATALOG_OBJECT = "catalog.json"
_gcs = None


def bucket():
    """The Python client picks up the Cloud Run service account from the
    metadata server; the gcloud CLI in a container does not."""
    global _gcs
    if not GCS_BUCKET:
        return None
    if _gcs is None:
        from google.cloud import storage
        _gcs = storage.Client().bucket(GCS_BUCKET)
    return _gcs


def load_catalog():
    """Container storage does not survive a restart, so the catalogue lives in
    the bucket and is pulled back on boot."""
    global catalog
    try:
        b = bucket()
        if b is not None:
            blob = b.blob(CATALOG_OBJECT)
            if blob.exists():
                catalog = json.loads(blob.download_as_bytes())
                print(f"catalogue restored: {len(catalog)} runs", flush=True)
                return
    except Exception as exc:
        print(f"catalogue restore failed: {exc}", flush=True)
    if CATALOG_FILE.exists():
        try:
            catalog = json.loads(CATALOG_FILE.read_text())
        except Exception:
            catalog = []


def save_catalog():
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(json.dumps(catalog, indent=2))
    try:
        b = bucket()
        if b is not None:
            b.blob(CATALOG_OBJECT).upload_from_filename(
                str(CATALOG_FILE), content_type="application/json")
    except Exception as exc:
        print(f"catalogue save failed: {exc}", flush=True)


async def wait_healthy(port):
    deadline = time.time() + BOOT_TIMEOUT
    async with aiohttp.ClientSession() as http:
        while time.time() < deadline:
            try:
                async with http.get(f"http://127.0.0.1:{port}/status",
                                    timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def start_session(agent):
    sid = uuid.uuid4().hex[:12]
    port = free_port()
    token = uuid.uuid4().hex
    env = dict(os.environ)
    env.update(PORT=str(port),
               QUNXIA_REC_KEEP_ALL="1",
               QUNXIA_SEND_HZ="10",              # nobody is watching a bench run
               QUNXIA_REC_MAX_BYTES=str(256 << 20),
               QUNXIA_RESET_TOKEN=token)
    proc = subprocess.Popen([PYTHON, str(SERVER)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sess = {"id": sid, "agent": agent, "port": port, "proc": proc,
            "state": "booting", "started": time.time(),
            "ends_at": time.time() + RUN_SECONDS, "video_url": None, "actions": 0,
            "keys": {}, "gaps": [], "first_action": None, "last_action": None,
            "reads": 0, "errors": 0, "reason": None}
    sessions[sid] = sess

    if not await wait_healthy(port):
        proc.kill()
        sess["state"] = "failed"
        raise web.HTTPBadGateway(
            text=json.dumps({"ok": False, "error": "session did not start"}),
            content_type="application/json")

    # Start every run in the opening room rather than at the title screen.
    # Creating a character means driving the 注音 IME, which measures knowledge
    # of input methods and not play, and it is where runs used to die.
    # /status answers as soon as the HTTP server is up, which is well before the
    # emulated machine has booted, and a savestate will not load into a machine
    # that is still starting. Retry until it takes.
    # The machine needs to finish booting before a savestate will load into it.
    await asyncio.sleep(float(os.environ.get("QUNXIA_BOOT_WAIT", "18")))
    sess["spawned"] = False
    async with aiohttp.ClientSession() as http:
        for _ in range(20):
            try:
                async with http.post(f"http://127.0.0.1:{port}/api/reset",
                                     params={"token": token},
                                     timeout=aiohttp.ClientTimeout(total=120)) as r:
                    if (await r.json()).get("restored"):
                        sess["spawned"] = True
                        break
            except Exception as exc:
                sess["error"] = f"spawn: {exc}"
            await asyncio.sleep(2)

    sess["state"] = "running"
    sess["playable"] = time.time()
    sess["ends_at"] = sess["playable"] + RUN_SECONDS  # clock starts once playable
    sess["task"] = asyncio.create_task(reaper(sid))
    return sess


async def reaper(sid):
    """Ends the run on whichever comes first: the clock, or a long silence."""
    sess = sessions[sid]
    try:
        while True:
            now = time.time()
            if now >= sess["ends_at"]:
                sess["reason"] = "time"
                break
            since = now - (sess["last_action"] or sess["playable"])
            if since >= IDLE_LIMIT:
                sess["reason"] = ("no action ever sent" if sess["last_action"] is None
                                  else "idle")
                sess["idle_for"] = round(since)
                break
            await asyncio.sleep(min(5, max(1, sess["ends_at"] - now)))
    except asyncio.CancelledError:
        return
    await finalize(sid)


async def finalize(sid):
    """Idempotent, and awaitable: a caller that arrives after the clock runs out
    waits for this so its reply carries the video link rather than a null."""
    sess = sessions.get(sid)
    if not sess:
        return
    if sess.get("final_task") and sess["state"] != "running":
        await asyncio.shield(sess["final_task"])
        return
    if sess["state"] != "running":
        return
    sess["final_task"] = asyncio.current_task()
    sess["state"] = "finalising"
    port = sess["port"]
    recording = None
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/api/recording",
                                timeout=aiohttp.ClientTimeout(total=120)) as r:
                recording = await r.json()
            async with http.get(f"http://127.0.0.1:{port}/status",
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
                sess["actions"] = (await r.json()).get("session", {}).get("actions", 0)
    except Exception as exc:
        sess["error"] = f"could not read recording: {exc}"

    sess["proc"].terminate()
    try:
        sess["proc"].wait(timeout=10)
    except Exception:
        sess["proc"].kill()

    if recording and recording.get("events"):
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        out = VIDEO_DIR / f"{sess['agent']}-{sid}.mp4"
        try:
            from render import render
            info = await asyncio.get_running_loop().run_in_executor(
                None, lambda: render(recording, out, sess["agent"]))
            sess["video"] = info
            sess["video_url"] = await upload(out)
        except Exception as exc:
            sess["error"] = f"render failed: {exc}"

    sess["state"] = "ended"
    catalog.insert(0, dict(metrics(sess), video_url=sess.get("video_url"),
                           video=sess.get("video"), error=sess.get("error")))
    save_catalog()


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def metrics(sess):
    """What a finished run is worth reporting on. Everything here is measured
    from the proxied traffic, so it holds for any agent regardless of harness."""
    playable = sess.get("playable") or sess["started"]
    first, last = sess.get("first_action"), sess.get("last_action")
    played = max(0.0, (last or playable) - playable)
    gaps = sess.get("gaps") or []
    keys = sess.get("keys") or {}
    # /status is authoritative, but it is unreachable if the child died; the
    # count taken off the wire covers that case.
    n = max(sess.get("actions", 0), sess.get("actions_seen", 0))
    return {
        "id": sess["id"], "agent": sess["agent"],
        "started": sess["started"],
        "seconds": round(time.time() - sess["started"]),
        "played": round(played),
        "budget": RUN_SECONDS,
        "boot": round(playable - sess["started"]),
        "actions": n,
        "reason": sess.get("reason") or "time",
        "idle_for": sess.get("idle_for"),
        "spawned": sess.get("spawned", False),
        # How long the agent took to make its first move. A slow start usually
        # means it spent the opening reading help rather than playing.
        "ttfa": round(first - playable, 2) if first else None,
        "aps": round(n / played, 3) if played > 0.5 and n else 0.0,
        "gap_p50": pct(gaps, 0.5),
        "gap_p95": pct(gaps, 0.95),
        "gap_max": round(max(gaps), 2) if gaps else None,
        "reads": sess.get("reads", 0),
        "errors": sess.get("errors", 0),
        # The action space the agent actually reached for, most used first.
        "keys": dict(sorted(keys.items(), key=lambda kv: -kv[1])),
        "distinct_keys": len(keys),
    }


async def upload(path: pathlib.Path):
    """Publish the video. Falls back to serving it from this host."""
    def put():
        b = bucket()
        if b is None:
            return None
        blob = b.blob(path.name)
        blob.upload_from_filename(str(path), content_type="video/mp4")
        blob.cache_control = "public, max-age=86400"
        blob.patch()
        return f"https://storage.googleapis.com/{GCS_BUCKET}/{path.name}"
    try:
        url = await asyncio.get_running_loop().run_in_executor(None, put)
        if url:
            return url
    except Exception as exc:
        print(f"upload failed: {exc}", flush=True)
    return f"{PUBLIC_BASE}/videos/{path.name}" if PUBLIC_BASE else f"/videos/{path.name}"


def human(sec):
    sec = int(sec or 0)
    if sec < 120:
        return f"{sec} seconds"
    m, s = divmod(sec, 60)
    unit = "minute" if m == 1 else "minutes"
    return f"{m} {unit}" + (f" {s}s" if s else "")


def why_text(sess):
    r = sess.get("reason") or "time"
    if r == "time":
        return f"the full {human(RUN_SECONDS)} budget was used"
    idle = human(sess.get("idle_for") or IDLE_LIMIT)
    if r == "no action ever sent":
        return (f"no action was ever sent - the run sat unplayed for {idle} "
                f"and was stopped")
    return (f"no action arrived for {idle}, so the run was stopped early. "
            f"Spending that long on a single step is a failure, not thinking")


def ended_payload(sess):
    played = round((sess.get("last_action") or sess.get("playable")
                    or sess["started"]) - (sess.get("playable") or sess["started"]))
    return {"ok": True, "ended": True,
            "message": "This benchmark run has ended. Stop playing.",
            "agent": sess["agent"], "budget_seconds": RUN_SECONDS,
            "played_seconds": played,
            "reason": sess.get("reason") or "time",
            "why": why_text(sess),
            "actions": max(sess.get("actions", 0), sess.get("actions_seen", 0)),
            "video_url": sess.get("video_url"),
            "catalog_url": (PUBLIC_BASE + "/catalog") if PUBLIC_BASE else "/catalog"}


# ------------------------------------------------------------------ http

async def api_new(request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    agent = (body.get("agent") or request.query.get("agent") or "agent")
    agent = "".join(c for c in agent if c.isalnum() or c in "-_.")[:32] or "agent"
    sess = await start_session(agent)
    base = str(request.url.origin()) + f"/s/{sess['id']}"
    return web.json_response({
        "ok": True, "session": sess["id"], "agent": agent,
        "base_url": base, "help_url": base + "/api/help",
        "seconds": RUN_SECONDS, "ends_at": sess["ends_at"],
        "spawned_in_game": sess.get("spawned", False),
        "idle_limit": IDLE_LIMIT,
        "message": f"You have {RUN_SECONDS // 60} minutes. Use {base}/api/... "
                   f"and read {base}/api/help first. Keep acting: if no action "
                   f"arrives for {IDLE_LIMIT // 60} minutes the run is stopped "
                   f"early and recorded as idle.",
    })


def note_activity(sess, method, tail, body):
    """Count what the agent did, straight off the wire."""
    path = tail.strip("/")
    if method == "GET" and path.startswith("api/screen"):
        sess["reads"] += 1
        return
    if method != "POST" or not path.startswith(ACTION_PATHS):
        return
    now = time.time()
    if sess["last_action"] is not None:
        sess["gaps"].append(now - sess["last_action"])
    else:
        sess["first_action"] = now
    sess["last_action"] = now
    sess["actions_seen"] = sess.get("actions_seen", 0) + 1
    try:
        d = json.loads(body or b"{}")
    except Exception:
        return
    ks = d.get("keys") or ([d["key"]] if d.get("key") else [])
    if path.startswith("api/wait"):
        ks = ["(wait)"]
    for k in ks:
        if isinstance(k, str):
            sess["keys"][k] = sess["keys"].get(k, 0) + 1


async def proxy(request):
    sid = request.match_info["sid"]
    sess = sessions.get(sid)
    if not sess:
        raise web.HTTPNotFound(text=json.dumps({"ok": False, "error": "no such session"}),
                               content_type="application/json")
    if sess["state"] != "running" or time.time() >= sess["ends_at"]:
        try:
            await asyncio.wait_for(finalize(sid), timeout=300)
        except Exception:
            pass
        return web.json_response(ended_payload(sess), status=410)

    tail = request.match_info.get("tail", "")
    data_peek = await request.read()
    note_activity(sess, request.method, tail, data_peek)
    url = f"http://127.0.0.1:{sess['port']}/{tail}"
    data = data_peek
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}
    headers.setdefault("X-Agent", sess["agent"])
    try:
        async with aiohttp.ClientSession() as http:
            async with http.request(request.method, url, params=request.query,
                                    data=data or None, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=180)) as r:
                raw = await r.read()
                out = web.Response(body=raw, status=r.status,
                                   content_type=r.content_type)
                if r.status >= 400:
                    sess["errors"] += 1
                out.headers["X-Bench-Remaining"] = str(int(sess["ends_at"] - time.time()))
                return out
    except Exception as exc:
        raise web.HTTPBadGateway(
            text=json.dumps({"ok": False, "error": str(exc)}),
            content_type="application/json")


async def api_sessions(_request):
    return web.json_response({"running": [
        {"id": s["id"], "agent": s["agent"], "state": s["state"],
         "actions": s.get("actions_seen", s.get("actions", 0)),
         "idle": round(time.time() - (s["last_action"] or s.get("playable")
                                      or s["started"])),
         "remaining": max(0, round(s["ends_at"] - time.time()))}
        for s in sessions.values() if s["state"] in ("running", "booting")]})


async def api_catalog(_request):
    return web.json_response({"runs": catalog})


async def page_catalog(_request):
    return web.FileResponse(ROOT / "catalog.html")


async def video_file(request):
    path = VIDEO_DIR / pathlib.Path(request.match_info["name"]).name
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def health(_request):
    return web.json_response({"ok": True, "running": len(
        [s for s in sessions.values() if s["state"] == "running"])})


async def ensure_start_state(app):
    """A savestate belongs to the core build that wrote it, so it cannot ship
    with the image and has to be made on first boot wherever this runs."""
    state = pathlib.Path(os.environ.get("QUNXIA_START_STATE",
                                        str(REPO / "saves" / "start.state")))
    if state.exists():
        print(f"start state present: {state}", flush=True)
        return
    print("no start state, playing the opening once to make one", flush=True)
    port, token = free_port(), uuid.uuid4().hex
    env = dict(os.environ)
    env.update(PORT=str(port), QUNXIA_RESET_TOKEN=token,
               QUNXIA_START_STATE=str(state))
    proc = subprocess.Popen([PYTHON, str(SERVER)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not await wait_healthy(port):
            raise RuntimeError("worker did not start")
        from bootstrap import build
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: build(f"http://127.0.0.1:{port}", token))
    except Exception as exc:
        print(f"bootstrap failed, runs will start at the title screen: {exc}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def main():
    load_catalog()
    app = web.Application(client_max_size=64 << 20)
    app.add_routes([
        web.get("/", page_catalog),
        web.get("/catalog", page_catalog),
        web.get("/health", health),
        web.post("/session", api_new),
        web.get("/api/sessions", api_sessions),
        web.get("/api/catalog", api_catalog),
        web.get("/videos/{name}", video_file),
        web.route("*", "/s/{sid}/{tail:.*}", proxy),
    ])
    app.on_startup.append(ensure_start_state)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8090")),
                access_log=None)


if __name__ == "__main__":
    main()
