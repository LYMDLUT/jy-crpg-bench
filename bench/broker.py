#!/usr/bin/env python3
"""Benchmark front door.

Spawns one isolated game process per agent and routes to it. That is all it
does: the run's clock, its teardown, its video and its catalogue entry all
belong to the session process itself (see server/warden.py), so this holds no
state worth losing and a node that dies takes only its own runs with it.

There is no catalogue here and no web page. The published catalogue is a JSON
object in the bucket, read directly by a static site.
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
RESULT_DIR = pathlib.Path(os.environ.get("QUNXIA_RESULT_DIR", "/tmp/qunxia-results"))
VIDEO_DIR = pathlib.Path(os.environ.get("QUNXIA_VIDEO_DIR", "/tmp/qunxia-videos"))
GCS_BUCKET = os.environ.get("QUNXIA_GCS_BUCKET", "")
PUBLIC_BASE = os.environ.get("QUNXIA_PUBLIC_BASE", "")
SITE = os.environ.get("QUNXIA_SITE", "https://hanxiao.io/jy-crpg-bench/")
RUN_SECONDS = int(os.environ.get("QUNXIA_RUN_SECONDS", "1200"))     # 20 minutes
# An agent that has not acted in this long is wedged, not thinking.
IDLE_LIMIT = int(os.environ.get("QUNXIA_IDLE_LIMIT", "600"))        # 10 minutes
BOOT_WAIT = float(os.environ.get("QUNXIA_BOOT_WAIT", "18"))
# Measured on 8 vCPU / 8Gi: 32 concurrent runs all held a full 70.09 fps with
# flat 1.13s action latency, and the container then OOMed at 33, killing every
# live run with it. CPU was never the limit; memory was, at roughly 123MB of
# game copy per run. This refuses the extra run instead of losing the others.
MAX_SESSIONS = int(os.environ.get("QUNXIA_MAX_SESSIONS", "24"))
# Every session gets its own copy of the game directory and its own libretro
# save directory. DOSBox Pure mounts the directory holding the content as a
# writable C:, and the skill tells agents to use the in-game save menu, so a
# shared directory would let one run's savegame land on another's. Measured at
# 123MB and 0.14s per copy, which is worth not having to reason about it.
GAME = os.environ.get("QUNXIA_GAME", str(REPO / "game" / "PLAY.BAT"))
WORK = pathlib.Path(os.environ.get("QUNXIA_WORK_DIR", "/tmp/qunxia-work"))
# How long to hold an agent's final call while its video renders and uploads.
# The run is over either way; this only decides whether the agent is handed the
# link or has to go and find it in the catalogue.
VIDEO_WAIT = float(os.environ.get("QUNXIA_VIDEO_WAIT", "300"))

# The catalogue page is static and served from another origin, so the two
# endpoints it reads have to say so.
CORS = {"Access-Control-Allow-Origin": "*"}

sessions: dict[str, dict] = {}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def result_of(sid):
    """The session process writes this the moment it calls its own run over."""
    f = RESULT_DIR / f"{sid}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


async def wait_published(sid, res):
    """The run writes its summary the moment it ends, then rewrites it once the
    video is up. Wait for the second write so the agent's last reply carries a
    link rather than a null."""
    if res.get("video_url") or res.get("error"):
        return res
    deadline = time.time() + VIDEO_WAIT
    while time.time() < deadline:
        await asyncio.sleep(2)
        later = result_of(sid)
        if later and (later.get("video_url") or later.get("error")):
            return later
    return res


async def wait_healthy(port, timeout=90):
    async with aiohttp.ClientSession() as http:
        for _ in range(int(timeout * 2)):
            try:
                async with http.get(f"http://127.0.0.1:{port}/status",
                                    timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


def make_workdir(sid):
    """A private, writable game directory for one run."""
    root = WORK / sid
    shutil.rmtree(root, ignore_errors=True)
    (root / "saves").mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(GAME).parent
    shutil.copytree(src, root / "game", dirs_exist_ok=True)
    return root / "game" / pathlib.Path(GAME).name, root / "saves"


def running_count():
    return sum(1 for s in sessions.values()
               if s["proc"].poll() is None and not result_of(s["id"]))


async def start_session(agent):
    live = running_count()
    if live >= MAX_SESSIONS:
        raise web.HTTPServiceUnavailable(
            text=json.dumps({
                "ok": False, "error": "at capacity",
                "running": live, "capacity": MAX_SESSIONS,
                "hint": "every machine is busy. Wait and POST /session again; "
                        "nothing is queued, so retry rather than hold."}),
            content_type="application/json", headers=CORS)
    sid = uuid.uuid4().hex[:12]
    port = free_port()
    token = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    game, saves = await loop.run_in_executor(None, make_workdir, sid)
    env = dict(os.environ)
    env.update(PORT=str(port),
               QUNXIA_GAME=str(game),
               QUNXIA_SAVES=str(saves),
               QUNXIA_REC_KEEP_ALL="1",
               QUNXIA_SEND_HZ="10",              # nobody is watching a bench run
               QUNXIA_REC_MAX_BYTES=str(256 << 20),
               QUNXIA_RESET_TOKEN=token,
               QUNXIA_BENCH="1",
               QUNXIA_BENCH_AGENT=agent,
               QUNXIA_BENCH_SID=sid,
               QUNXIA_BENCH_BUDGET=str(RUN_SECONDS),
               QUNXIA_BENCH_IDLE=str(IDLE_LIMIT),
               QUNXIA_RESULT_DIR=str(RESULT_DIR),
               QUNXIA_BENCH_SITE=SITE)
    proc = subprocess.Popen([PYTHON, str(SERVER)], env=env, cwd=str(REPO / "server"))
    sess = {"id": sid, "agent": agent, "port": port, "proc": proc,
            "work": WORK / sid,
            "started": time.time(), "ends_at": time.time() + RUN_SECONDS}
    sessions[sid] = sess

    if not await wait_healthy(port):
        proc.kill()
        shutil.rmtree(WORK / sid, ignore_errors=True)
        raise web.HTTPBadGateway(
            text=json.dumps({"ok": False, "error": "session did not start"}),
            content_type="application/json")

    # Start every run in the opening room rather than at the title screen.
    # Creating a character means driving the 注音 IME, which measures knowledge
    # of input methods and not play, and it is where runs used to die. A
    # savestate will not load into a machine that is still booting, so retry.
    await asyncio.sleep(BOOT_WAIT)
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
    sess["ends_at"] = time.time() + RUN_SECONDS       # clock starts once playable
    return sess


def ended_payload(sess, res):
    """The run published its own summary; pass it back rather than guessing."""
    keep = ("reason", "why", "actions", "played", "aps", "video_url", "error")
    return dict({k: res[k] for k in keep if res and k in res},
                ok=True, ended=True, agent=sess["agent"],
                message="This benchmark run has ended. Stop playing.",
                catalog_url=SITE)


# ------------------------------------------------------------------ http

def public_origin(request):
    """Cloud Run terminates TLS in front of us, so request.url.scheme is http.
    Handing that back made agents POST to http, get 302'd to https, and have
    the redirect turn their POST into a GET."""
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    return f"{proto or request.url.scheme}://{host or request.host}"


async def api_new(request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    agent = (body.get("agent") or request.query.get("agent") or "").strip()
    agent = "".join(c for c in agent if c.isalnum() or c in "-_.")[:40]
    if not agent:
        return web.json_response(
            {"ok": False, "error": "name yourself first",
             "hint": 'POST {"agent": "<the model you are>"} - the name is what '
                     'the catalogue lists this run under'}, status=400)
    sess = await start_session(agent)
    base = public_origin(request) + f"/s/{sess['id']}"
    return web.json_response({
        "ok": True, "session": sess["id"], "agent": agent,
        "base_url": base, "help_url": base + "/api/help",
        "seconds": RUN_SECONDS, "ends_at": sess["ends_at"],
        "idle_limit": IDLE_LIMIT,
        "spawned_in_game": sess.get("spawned", False),
        "catalog_url": SITE,
        "message": f"You are in the game as '{agent}'. You have "
                   f"{RUN_SECONDS // 60} minutes. Read {base}/api/help, then "
                   f"play with {base}/api/... . Keep acting: if no action "
                   f"arrives for {IDLE_LIMIT // 60} minutes the run is stopped "
                   f"early and listed as idle.",
    })


async def proxy(request):
    sid = request.match_info["sid"]
    sess = sessions.get(sid)
    if not sess:
        raise web.HTTPNotFound(
            text=json.dumps({"ok": False, "error": "no such session",
                             "hint": "POST /session to start one"}),
            content_type="application/json")

    res = result_of(sid)
    if res or sess["proc"].poll() is not None:
        if res:
            res = await wait_published(sid, res)
        return web.json_response(ended_payload(sess, res), status=410)

    tail = request.match_info.get("tail", "")
    url = f"http://127.0.0.1:{sess['port']}/{tail}"

    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await spectate(request, sess, url)

    data = await request.read()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}
    headers.setdefault("X-Agent", sess["agent"])
    try:
        async with aiohttp.ClientSession() as http:
            async with http.request(request.method, url, params=request.query,
                                    data=data or None, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=180)) as r:
                out = web.Response(body=await r.read(), status=r.status,
                                   content_type=r.content_type)
                out.headers["X-Bench-Remaining"] = str(
                    max(0, int(sess["ends_at"] - time.time())))
                return out
    except Exception as exc:
        # The process may have published and exited between the two checks.
        res = result_of(sid)
        if res:
            return web.json_response(
                ended_payload(sess, await wait_published(sid, res)), status=410)
        raise web.HTTPBadGateway(
            text=json.dumps({"ok": False, "error": str(exc)}),
            content_type="application/json")


async def spectate(request, sess, url):
    """Watch a run in progress. Anything the viewer sends is dropped rather
    than forwarded, so a spectator cannot touch the game even with a hand
    written socket - read only is a property of this proxy, not of the page."""
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await ws.prepare(request)
    sess["watchers"] = sess.get("watchers", 0) + 1
    try:
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(url, max_msg_size=0, heartbeat=30) as up:
                async def downstream():
                    async for m in up:
                        if m.type == aiohttp.WSMsgType.BINARY:
                            await ws.send_bytes(m.data)
                        elif m.type == aiohttp.WSMsgType.TEXT:
                            await ws.send_str(m.data)
                pump = asyncio.create_task(downstream())
                try:
                    async for _ in ws:
                        pass                      # deliberately ignored
                finally:
                    pump.cancel()
    except Exception:
        pass
    finally:
        sess["watchers"] = max(0, sess.get("watchers", 1) - 1)
        await ws.close()
    return ws


async def api_sessions(_request):
    now = time.time()
    return web.json_response(
        {"capacity": MAX_SESSIONS, "running": [
            {"id": s["id"], "agent": s["agent"],
             "started": s["started"], "watchers": s.get("watchers", 0),
             "actions": s.get("live_actions", 0),
             "uptime": round(s.get("live_uptime", 0)),
             "remaining": max(0, round(s["ends_at"] - now))}
            for s in sessions.values()
            if s["proc"].poll() is None and not result_of(s["id"])]},
        headers=CORS)


async def video_file(request):
    """Only used when no bucket is configured, ie local development."""
    name = pathlib.Path(request.match_info["name"]).name
    path = VIDEO_DIR / name
    if not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def api_catalog(_request):
    """The published catalogue lives in the bucket; this is the local mirror
    so the static page can be developed without one."""
    if GCS_BUCKET:
        raise web.HTTPFound(
            f"https://storage.googleapis.com/{GCS_BUCKET}/catalog.json")
    f = pathlib.Path(os.environ.get("QUNXIA_CATALOG", "/tmp/qunxia-catalog.json"))
    runs = json.loads(f.read_text()) if f.exists() else []
    return web.json_response({"runs": runs}, headers=CORS)


async def health(_request):
    return web.json_response({
        "ok": True, "running": running_count(), "capacity": MAX_SESSIONS,
        "budget": RUN_SECONDS, "idle_limit": IDLE_LIMIT, "site": SITE},
        headers=CORS)


async def index(_request):
    """No dashboard here. The site is static and lives elsewhere."""
    raise web.HTTPFound(SITE)


async def sweep(app):
    """Housekeeping, on the broker's own clock rather than a caller's.

    Reclaims a finished run's 123MB game copy once the process that owned it is
    gone - the run cannot do that itself, since it is still holding those files
    open as it exits. Also refreshes the live action counts, cached here so a
    page full of viewers costs the same as one.
    """
    tick = 0
    while True:
        await asyncio.sleep(3)
        tick += 1
        async with aiohttp.ClientSession() as http:
            for s in list(sessions.values()):
                if s["proc"].poll() is not None or result_of(s["id"]):
                    continue
                try:
                    async with http.get(f"http://127.0.0.1:{s['port']}/status",
                                        timeout=aiohttp.ClientTimeout(total=3)) as r:
                        d = (await r.json()).get("session", {})
                        s["live_actions"] = d.get("actions", 0)
                        s["live_uptime"] = d.get("uptime_s", 0)
                except Exception:
                    pass
        if tick % 10:
            continue
        for s in list(sessions.values()):
            work = s.get("work")
            if work and s["proc"].poll() is not None and work.exists():
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda w=work: shutil.rmtree(w, ignore_errors=True))
                print(f"reclaimed {work}", flush=True)


async def spawn_sweep(app):
    app["sweep"] = asyncio.create_task(sweep(app))


async def ensure_start_state(app):
    """The savestate is tied to the core build, so it cannot be shipped in the
    image. Author it here, once, on whatever machine this is."""
    state = pathlib.Path(os.environ.get(
        "QUNXIA_START_STATE", str(REPO / "saves" / "start.state")))
    if state.exists():
        print(f"start state present: {state}", flush=True)
        return
    print("no start state, playing the opening once to make one", flush=True)
    port, token = free_port(), uuid.uuid4().hex
    env = dict(os.environ)
    env.update(PORT=str(port), QUNXIA_RESET_TOKEN=token,
               QUNXIA_START_STATE=str(state))
    env.pop("QUNXIA_BENCH", None)              # the authoring run is not a run
    proc = subprocess.Popen([PYTHON, str(SERVER)], env=env, cwd=str(REPO / "server"),
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
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg") is None:
        print("warning: ffmpeg not on PATH, runs will not render", flush=True)
    app = web.Application(client_max_size=64 << 20)
    app.add_routes([
        web.get("/", index),
        web.get("/health", health),
        web.post("/session", api_new),
        web.get("/api/sessions", api_sessions),
        web.get("/api/catalog", api_catalog),
        web.get("/videos/{name}", video_file),
        web.route("*", "/s/{sid}/{tail:.*}", proxy),
    ])
    app.on_startup.append(ensure_start_state)
    app.on_startup.append(spawn_sweep)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                access_log=None)


if __name__ == "__main__":
    main()
