#!/usr/bin/env python3
"""Headless 金庸群俠傳 for the browser.

Runs the DOS game through DOSBox Pure with no display, and streams the VGA
framebuffer to a canvas as deflated 16x10 tile deltas. Keyboard input comes
back over the same socket. No audio.
"""
import asyncio
import base64
import collections
import ctypes
import io
import json
import os
import pathlib
import sys
import threading
import time
import traceback
import zlib

from aiohttp import WSMsgType, web
from PIL import Image

from prompt import system_prompt

ROOT = pathlib.Path(__file__).resolve().parent
LIB = ctypes.CDLL(str(ROOT / "libqunxia.so"))
CORE = os.environ.get("QUNXIA_CORE", str(ROOT.parent / "cores" / "dosbox_pure_libretro.so"))
GAME = os.environ.get("QUNXIA_GAME", str(ROOT.parent / "game" / "PLAY.BAT"))
SAVES = os.environ.get("QUNXIA_SAVES", str(ROOT.parent / "saves"))
PORT = int(os.environ.get("PORT", "8080"))
SEND_HZ = float(os.environ.get("QUNXIA_SEND_HZ", "20"))

LIB.core_set_option.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
LIB.core_init.argtypes = [ctypes.c_char_p] * 3
LIB.core_init.restype = ctypes.c_bool
LIB.core_key.argtypes = [ctypes.c_int, ctypes.c_bool]
LIB.core_fps.restype = ctypes.c_double
LIB.core_frame_serial.restype = ctypes.c_uint64
LIB.core_last_error.restype = ctypes.c_char_p
LIB.fb_encode_delta.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
LIB.fb_encode_delta.restype = ctypes.c_int
LIB.core_frame_hash.restype = ctypes.c_uint64
LIB.core_reset.restype = None
LIB.fb_reset.restype = None
LIB.fb_snapshot.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
LIB.fb_snapshot.restype = ctypes.c_int
LIB.core_save_state.argtypes = [ctypes.c_char_p]
LIB.core_save_state.restype = ctypes.c_bool
LIB.core_load_state.argtypes = [ctypes.c_char_p]
LIB.core_load_state.restype = ctypes.c_bool

BUF = ctypes.create_string_buffer(4 << 20)

# Key name -> RETROK. Same vocabulary as the native runner.
KEYS = {
    "up": 273, "down": 274, "right": 275, "left": 276,
    "enter": 13, "return": 13, "ok": 13, "space": 32,
    "esc": 27, "escape": 27, "cancel": 27,
    "tab": 9, "backspace": 8, "delete": 127,
    "shift": 304, "ctrl": 306, "alt": 308,
    "home": 278, "end": 279, "pageup": 280, "pagedown": 281,
}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYS[_c] = 97 + _i
for _d in range(10):
    KEYS[str(_d)] = 48 + _d
for _f in range(1, 13):
    KEYS[f"f{_f}"] = 281 + _f
for _k, _v in {";": 59, "'": 39, ",": 44, ".": 46, "/": 47, "-": 45, "=": 61,
               "[": 91, "]": 93, "\\": 92, "`": 96}.items():
    KEYS[_k] = _v
for _n in range(10):                      # numpad; the game accepts these for movement
    KEYS[f"kp{_n}"] = 256 + _n
KEYS["kpenter"] = 271
# The four movement axes are screen diagonals. Verified byte-identical to the
# arrows, so these are aliases that say what actually happens on screen.
for _alias, _code in {"upright": 273, "ne": 273,      # == up    == kp9
                      "downleft": 274, "sw": 274,     # == down  == kp1
                      "downright": 275, "se": 275,    # == right == kp3
                      "upleft": 276, "nw": 276}.items():  # == left == kp7
    KEYS[_alias] = _code

# Native resolution only, so the largest frame the core produces is 640x400.
SNAP = ctypes.create_string_buffer(640 * 400 * 3 + 4096)
api_lock = asyncio.Lock()     # one action at a time; the game is single-player
paused = threading.Event()    # held while the core is rebooted, so retro_reset
                              # is never called underneath a running retro_run

clients: set[web.WebSocketResponse] = set()
stats = {"frames": 0, "sent": 0, "bytes": 0, "tiles": 0, "dropped": 0,
         "pump_errors": 0, "last_error": "", "pump_ticks": 0, "pump_stage": "init",
         "queued": 0}
SEND_TIMEOUT = float(os.environ.get("QUNXIA_SEND_TIMEOUT", "3"))
LOCK_TIMEOUT = float(os.environ.get("QUNXIA_LOCK_TIMEOUT", "30"))

# Everything anyone does to this session, so the page can show who is doing
# what. The game is shared, so this doubles as "why did the screen just move".
history: collections.deque = collections.deque(maxlen=300)
_seq = [0]
THUMB_W = 150
THUMB_KEEP = 40          # only the newest entries carry an image, to bound memory


def make_thumb():
    """Small WebP of the current screen, for the activity panel."""
    w = ctypes.c_int(0)
    h = ctypes.c_int(0)
    n = LIB.fb_snapshot(SNAP, len(SNAP), 1, ctypes.byref(w), ctypes.byref(h))
    if n <= 0:
        return None
    img = Image.frombytes("RGB", (w.value, h.value), SNAP.raw[:n])
    img = img.resize((THUMB_W, max(1, round(THUMB_W * h.value / w.value))), Image.NEAREST)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=72, method=0)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()


def log_action(src, verb, target, detail="", ok=True, thumb=False):
    _seq[0] += 1
    entry = {"id": _seq[0], "at": time.time(), "src": src, "verb": verb,
             "target": str(target)[:60], "detail": str(detail)[:60], "ok": ok}
    if thumb:
        try:
            entry["thumb"] = make_thumb()
        except Exception:
            pass
        # drop images from older entries so the buffer stays small
        withimg = [e for e in history if e.get("thumb")]
        for e in withimg[:max(0, len(withimg) - THUMB_KEEP + 1)]:
            e.pop("thumb", None)
    history.append(entry)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return entry
    asyncio.create_task(broadcast_log(entry))
    return entry


async def _send_one(ws, data, text):
    """One send, bounded. A peer that vanished without closing the TCP
    connection blocks forever once its window fills, so every send needs a
    deadline of its own."""
    try:
        async with asyncio.timeout(SEND_TIMEOUT):
            if text:
                await ws.send_str(data)
            else:
                await ws.send_bytes(data)
        return ws, True
    except Exception:
        return ws, False


async def fanout(data, text=False):
    """Send to every client at once and drop the ones that fail.

    Sending serially meant a single stuck client stalled the broadcast for
    everyone, which is how streaming died while the emulator kept running.
    """
    targets = []
    for ws in list(clients):
        if ws.closed:
            clients.discard(ws)
        else:
            targets.append(ws)
    if not targets:
        return
    for ws, ok in await asyncio.gather(*(_send_one(ws, data, text) for ws in targets)):
        if not ok:
            clients.discard(ws)
            stats["dropped"] += 1


async def broadcast_log(entry):
    await fanout(json.dumps({"t": "log", "e": [entry]}), text=True)


def emulate():
    """Own thread. ctypes drops the GIL for each call, so asyncio keeps running."""
    budget = 1.0 / max(1.0, LIB.core_fps())
    nxt = time.perf_counter()
    while True:
        if paused.is_set():
            time.sleep(0.02)
            nxt = time.perf_counter()
            continue
        LIB.core_run_frame()
        stats["frames"] += 1
        nxt += budget
        delay = nxt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        elif delay < -0.25:
            nxt = time.perf_counter()


async def pump():
    """Encode a delta and fan it out, only when something actually changed.

    The body is guarded because a task created with create_task dies silently
    on an unhandled exception, and a dead pump looks exactly like a working
    server with a frozen picture.
    """
    period = 1.0 / SEND_HZ
    last_serial = -1
    while True:
        try:
            await asyncio.sleep(period)
            stats["pump_ticks"] += 1
            if not clients:
                continue
            stats["pump_stage"] = "serial"
            serial = LIB.core_frame_serial()
            if serial == last_serial:
                continue          # picture is identical, send nothing at all
            last_serial = serial
            stats["pump_stage"] = "encode"
            n = LIB.fb_encode_delta(BUF, len(BUF), 0)
            if n <= 0:
                continue
            count = int.from_bytes(BUF.raw[11:13], "little")
            if count == 0:
                continue
            stats["pump_stage"] = "compress"
            payload = zlib.compress(BUF.raw[:n], 6)
            stats["sent"] += 1
            stats["bytes"] += len(payload)
            stats["tiles"] += count
            stats["pump_stage"] = "fanout"
            await fanout(payload)
            stats["pump_stage"] = "idle"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats["pump_errors"] += 1
            stats["last_error"] = f"{type(exc).__name__}: {exc}"
            print("pump error:", repr(exc), file=sys.stderr, flush=True)
            traceback.print_exc()
            await asyncio.sleep(0.5)


async def reap():
    """Drop clients that closed without a handshake. Without this they linger,
    are counted, and are sent every frame."""
    while True:
        await asyncio.sleep(15)
        for ws in list(clients):
            if ws.closed:
                clients.discard(ws)


async def send_keyframe(ws):
    n = LIB.fb_encode_delta(BUF, len(BUF), 1)
    if n > 0:
        await ws.send_bytes(zlib.compress(BUF.raw[:n], 6))


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await ws.prepare(request)
    clients.add(ws)
    await send_keyframe(ws)
    if history:
        await ws.send_str(json.dumps({"t": "log", "e": list(history)[-80:]}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            d = msg.json()
            t = d.get("t")
            if t == "key":
                name = str(d.get("k", "")).lower()
                code = KEYS.get(name)
                if code:
                    down = bool(d.get("down"))
                    LIB.core_key(code, down)
                    if down:                      # keyup would just double every line
                        log_action("web", "KEY", name)
            elif t == "tap":
                name = str(d.get("k", "")).lower()
                code = KEYS.get(name)
                if code:
                    log_action("web", "KEY", name)
                    LIB.core_key(code, True)
                    await asyncio.sleep(0.06)
                    LIB.core_key(code, False)
            elif t == "keyframe":
                await send_keyframe(ws)
    finally:
        clients.discard(ws)
    return ws


def snapshot(fmt="png"):
    """The screen at native size.

    PNG by default: WebP is smaller and equally lossless, but PNG is what
    vision stacks handle most reliably, and being read correctly matters more
    here than the bytes. ?format=webp is there when size does matter.
    """
    w = ctypes.c_int(0)
    h = ctypes.c_int(0)
    n = LIB.fb_snapshot(SNAP, len(SNAP), 1, ctypes.byref(w), ctypes.byref(h))
    if n <= 0:
        return None, 0, 0, ""
    img = Image.frombytes("RGB", (w.value, h.value), SNAP.raw[:n])
    out = io.BytesIO()
    if fmt == "webp":
        img.save(out, "WEBP", lossless=True, method=4)
        mime = "image/webp"
    else:
        img.save(out, "PNG", optimize=True)
        mime = "image/png"
    return out.getvalue(), w.value, h.value, mime


async def settle(baseline, react=30, stable=9, maxframes=120):
    """Wait for the game to react, then for the picture to hold still.

    Three ways to be done. The picture stops changing; or it starts cycling,
    which is what a blinking cursor or an idle sprite loop does and which never
    goes still; or nothing happened at all within the react budget. Without the
    cycle test every animated screen ran to maxframes, and that wait is held
    under the action lock, so it set the floor on how fast several agents can
    take turns.
    """
    ft = 1.0 / max(1.0, LIB.core_fps())
    reacted = react == 0
    last, runs, n = baseline, 0, 0
    seen: dict[int, int] = {}
    while n < maxframes:
        await asyncio.sleep(ft)
        n += 1
        h = LIB.core_frame_hash()
        if not reacted:
            if h != baseline:
                reacted, runs, last = True, 0, h
                seen = {h: n}
            elif n >= react:
                break
            continue
        if h == last:
            runs += 1
            if n >= 6 and runs >= stable:
                break
        else:
            runs = 0
            last = h
            first = seen.get(h)
            if first is not None and n - first >= stable:
                break                      # animation loop, it will never settle
            seen.setdefault(h, n)
    return n, reacted


async def tap(code, hold_frames):
    ft = 1.0 / max(1.0, LIB.core_fps())
    LIB.core_key(code, True)
    await asyncio.sleep(ft * max(1, hold_frames))
    LIB.core_key(code, False)
    await asyncio.sleep(ft * 2)


async def run_action(request, steps, note, verb="KEY"):
    """steps: list of (retrok, hold_frames) or ("wait", seconds).

    Deliberately does not return a screenshot. Encoding a PNG for every
    keypress cost real CPU on a shared-core box and most of those images were
    never looked at. Ask for /api/screen when you actually want to see.

    One action runs at a time so the game stays coherent when several agents
    act on it, but a caller waiting behind others is told so instead of being
    left to hang.
    """
    stats["queued"] += 1
    try:
        await asyncio.wait_for(api_lock.acquire(), timeout=LOCK_TIMEOUT)
    except asyncio.TimeoutError:
        return web.json_response(
            {"ok": False, "error": "busy", "queued": stats["queued"],
             "hint": "another agent holds the game; retry"}, status=503)
    finally:
        stats["queued"] -= 1

    try:
        baseline = LIB.core_frame_hash()
        for kind, val in steps:
            if kind == "wait":
                await asyncio.sleep(val)
            else:
                await tap(kind, val)
        waited, changed = await settle(baseline)
        log_action(actor(request), verb, note)
    finally:
        api_lock.release()

    return web.json_response({
        "ok": True, "action": note, "changed": changed,
        "width": LIB.core_width(), "height": LIB.core_height(),
        "frame": LIB.core_frame_serial(), "settled_frames": waited,
    })


async def body_of(request):
    try:
        return await request.json()
    except Exception:
        return {}


def keycode(name):
    return KEYS.get(str(name).strip().lower())


def actor(request):
    """Optional agent name, so several agents on one session are told apart."""
    name = (request.headers.get("X-Agent") or request.query.get("agent") or "api")
    return "".join(c for c in name if c.isalnum() or c in "-_.")[:16] or "api"


async def api_key(request):
    d = await body_of(request)
    code = keycode(d.get("key", ""))
    if not code:
        return web.json_response({"ok": False, "error": "unknown key"}, status=400)
    hold = int(d.get("hold", 4))
    times = max(1, min(int(d.get("times", 1)), 100))
    steps = []
    for i in range(times):
        steps.append((code, hold))
        if i != times - 1:
            steps.append(("wait", 0.08))
    return await run_action(request, steps, str(d.get("key")) + (f" x{times}" if times > 1 else ""))


async def api_keys(request):
    d = await body_of(request)
    names = d.get("keys") or []
    codes = [keycode(k) for k in names]
    if not names or any(c is None for c in codes):
        return web.json_response({"ok": False, "error": "unknown key in list"}, status=400)
    hold = int(d.get("hold", 4))
    steps = []
    for i, c in enumerate(codes):
        steps.append((c, hold))
        if i != len(codes) - 1:
            steps.append(("wait", 0.08))
    return await run_action(request, steps, " ".join(map(str, names)), verb="KEYS")


async def api_text(request):
    d = await body_of(request)
    text = str(d.get("text", ""))
    if not text:
        return web.json_response({"ok": False, "error": "text required"}, status=400)
    steps = []
    for ch in text:
        c = keycode(ch)
        if c:
            steps.append((c, 3))
            steps.append(("wait", 0.05))
    return await run_action(request, steps, text, verb="TEXT")


async def api_wait(request):
    d = await body_of(request)
    ms = max(0, min(int(d.get("ms", 1000)), 60000))
    return await run_action(request, [("wait", ms / 1000)], f"{ms}ms", verb="WAIT")


async def api_screen(request):
    """The only way to look at the screen. JSON, or ?format=png|webp for bytes."""
    fmt = request.query.get("format", "")
    log_action(actor(request), "GET", "screen", thumb=True)
    data, w, h, mime = snapshot("webp" if fmt == "webp" else "png")
    if not data:
        return web.json_response({"ok": False, "error": "no frame"}, status=503)
    if fmt in ("png", "webp"):
        return web.Response(body=data, content_type=mime)
    return web.json_response({
        "ok": True, "width": LIB.core_width(), "height": LIB.core_height(),
        "frame": LIB.core_frame_serial(), "image_width": w, "image_height": h,
        "image": f"data:{mime};base64," + base64.b64encode(data).decode(),
    })


def base_url(request):
    forwarded = request.headers.get("X-Forwarded-Proto")
    scheme = forwarded or request.scheme
    return f"{scheme}://{request.host}"


async def api_reset(request):
    """Hidden. Reboots the emulated machine back to the title screen and wipes
    the activity log. Unlisted in /api/help and 404s unless the token matches,
    so a visitor who stumbles on the path cannot wipe someone's game."""
    want = os.environ.get("QUNXIA_RESET_TOKEN")
    got = request.query.get("token") or request.headers.get("X-Reset-Token")
    if not want or got != want:
        raise web.HTTPNotFound()

    async with api_lock:
        paused.set()
        await asyncio.sleep(0.1)          # let the in-flight frame finish
        try:
            LIB.core_release_all_keys()
            LIB.core_reset()
            LIB.fb_reset()
        finally:
            paused.clear()
        history.clear()
        _seq[0] = 0
        await asyncio.sleep(1.5)          # give the machine a moment to start booting

    await fanout(json.dumps({"t": "clear"}), text=True)
    for ws in list(clients):
        try:
            async with asyncio.timeout(SEND_TIMEOUT):
                await send_keyframe(ws)
        except Exception:
            clients.discard(ws)
    log_action("api", "RESET", "rebooted to title screen")
    return web.json_response({"ok": True, "reset": True})


async def api_history(_request):
    return web.json_response({"history": list(history)})


async def api_help(request):
    lang = request.query.get("lang", "en")
    log_action(actor(request), "GET", f"help ({lang})")
    return web.Response(text=system_prompt(base_url(request), lang),
                        content_type="text/plain", charset="utf-8")


async def index(_request):
    return web.FileResponse(ROOT / "index.html")


async def status(_request):
    return web.json_response({
        "width": LIB.core_width(), "height": LIB.core_height(),
        "fps": round(LIB.core_fps(), 3), "frame": LIB.core_frame_serial(),
        "clients": len(clients), **stats,
    })


def main():
    os.makedirs(SAVES, exist_ok=True)
    # Measured on this class of VM: 77000 cycles leaves only 1.75x headroom over
    # the 70.09 fps the core needs, which a shared-core instance cannot hold once
    # burst credits run out. 26800 (486DX2-66, period-correct for a 1996 game)
    # runs 6.7x faster than needed, so ~15% of a core.
    for k, v in {
        "dosbox_pure_cycles": os.environ.get("QUNXIA_CYCLES", "26800"),
        "dosbox_pure_sblaster_type": "none",   # no audio is streamed; do not synthesise it
        "dosbox_pure_midi": "disabled",
    }.items():
        LIB.core_set_option(k.encode(), v.encode())
    if not LIB.core_init(CORE.encode(), GAME.encode(), SAVES.encode()):
        raise SystemExit("core_init failed: " + LIB.core_last_error().decode())
    threading.Thread(target=emulate, daemon=True).start()

    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/ws", ws_handler),
        web.get("/status", status),
        web.get("/api/screen", api_screen),
        web.get("/api/help", api_help),
        web.get("/api/history", api_history),
        web.post("/api/reset", api_reset),
        web.post("/api/key", api_key),
        web.post("/api/keys", api_keys),
        web.post("/api/text", api_text),
        web.post("/api/wait", api_wait),
    ])
    # on_startup handlers are awaited, so the pump has to be detached as a task
    # rather than returned, or startup blocks on a loop that never ends.
    async def _spawn_pump(a):
        a["pump"] = asyncio.create_task(pump())
        a["reaper"] = asyncio.create_task(reap())
    app.on_startup.append(_spawn_pump)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)


if __name__ == "__main__":
    main()
