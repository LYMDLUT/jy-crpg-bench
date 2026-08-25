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
import struct
import threading
import time
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

SNAP = ctypes.create_string_buffer(6 * 6 * 640 * 400 * 3)
api_lock = asyncio.Lock()     # one action at a time; the game is single-player

clients: set[web.WebSocketResponse] = set()
stats = {"frames": 0, "sent": 0, "bytes": 0, "tiles": 0}

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


async def broadcast_log(entry):
    msg = json.dumps({"t": "log", "e": [entry]})
    for ws in list(clients):
        if ws.closed:
            clients.discard(ws)
            continue
        try:
            await ws.send_str(msg)
        except Exception:
            clients.discard(ws)


def emulate():
    """Own thread. ctypes drops the GIL for each call, so asyncio keeps running."""
    budget = 1.0 / max(1.0, LIB.core_fps())
    nxt = time.perf_counter()
    while True:
        LIB.core_run_frame()
        stats["frames"] += 1
        nxt += budget
        delay = nxt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        elif delay < -0.25:
            nxt = time.perf_counter()


async def pump():
    """Encode a delta and fan it out, only when something actually changed."""
    period = 1.0 / SEND_HZ
    last_serial = -1
    while True:
        await asyncio.sleep(period)
        if not clients:
            continue
        serial = LIB.core_frame_serial()
        if serial == last_serial:
            continue          # picture is identical, send nothing at all
        last_serial = serial
        n = LIB.fb_encode_delta(BUF, len(BUF), 0)
        if n <= 0:
            continue
        count = int.from_bytes(BUF.raw[11:13], "little")
        if count == 0:
            continue
        payload = zlib.compress(BUF.raw[:n], 6)
        stats["sent"] += 1
        stats["bytes"] += len(payload)
        stats["tiles"] += count
        for ws in list(clients):
            if ws.closed:
                clients.discard(ws)
                continue
            try:
                await ws.send_bytes(payload)
            except Exception:
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


def encode_png(w, h, rgb):
    """Minimal PNG writer: avoids pulling in an image library for one job."""
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def snapshot(scale=2):
    w = ctypes.c_int(0)
    h = ctypes.c_int(0)
    n = LIB.fb_snapshot(SNAP, len(SNAP), scale, ctypes.byref(w), ctypes.byref(h))
    if n <= 0:
        return None, 0, 0
    return encode_png(w.value, h.value, SNAP.raw[:n]), w.value, h.value


async def settle(baseline, react=30, stable=9, maxframes=150):
    """Wait for the game to react, then for the picture to hold still.

    The emulator free-runs on its own thread, so waiting here is just wall
    clock. Without the react phase we would snapshot the screen from before the
    action, and dialogue is drawn with a typewriter effect that pauses between
    glyphs, so `stable` has to be generous or lines come back half-written.
    """
    ft = 1.0 / max(1.0, LIB.core_fps())
    reacted = react == 0
    last, runs, n = baseline, 0, 0
    while n < maxframes:
        await asyncio.sleep(ft)
        n += 1
        h = LIB.core_frame_hash()
        if not reacted:
            if h != baseline:
                reacted, runs, last = True, 0, h
            elif n >= react:
                break
        else:
            runs = runs + 1 if h == last else 0
            last = h
            if n >= 6 and runs >= stable:
                break
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
    """
    async with api_lock:
        baseline = LIB.core_frame_hash()
        for kind, val in steps:
            if kind == "wait":
                await asyncio.sleep(val)
            else:
                await tap(kind, val)
        waited, changed = await settle(baseline)
        log_action("api", verb, note)
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
    """The only way to look at the screen. JSON by default, ?format=png for bytes."""
    scale = max(1, min(6, int(request.query.get("scale", 2))))
    log_action("api", "GET", "screen", thumb=True)
    png, w, h = snapshot(scale)
    if not png:
        return web.json_response({"ok": False, "error": "no frame"}, status=503)
    if request.query.get("format") == "png":
        return web.Response(body=png, content_type="image/png")
    return web.json_response({
        "ok": True, "width": LIB.core_width(), "height": LIB.core_height(),
        "frame": LIB.core_frame_serial(), "image_width": w, "image_height": h,
        "image": "data:image/png;base64," + base64.b64encode(png).decode(),
    })


def base_url(request):
    forwarded = request.headers.get("X-Forwarded-Proto")
    scheme = forwarded or request.scheme
    return f"{scheme}://{request.host}"


async def api_history(_request):
    return web.json_response({"history": list(history)})


async def api_help(request):
    lang = request.query.get("lang", "en")
    log_action("api", "GET", f"help ({lang})")
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
        web.post("/api/key", api_key),
        web.post("/api/keys", api_keys),
        web.post("/api/text", api_text),
        web.post("/api/wait", api_wait),
    ])
    # on_startup handlers are awaited, so the pump has to be detached as a task
    # rather than returned, or startup blocks on a loop that never ends.
    async def _spawn_pump(a):
        a["pump"] = asyncio.create_task(pump())
    app.on_startup.append(_spawn_pump)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)


if __name__ == "__main__":
    main()
