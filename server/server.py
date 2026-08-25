#!/usr/bin/env python3
"""Headless 金庸群俠傳 for the browser.

Runs the DOS game through DOSBox Pure with no display, and streams the VGA
framebuffer to a canvas as deflated 16x10 tile deltas. Keyboard input comes
back over the same socket. No audio.
"""
import asyncio
import ctypes
import os
import pathlib
import threading
import time
import zlib

from aiohttp import WSMsgType, web

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

clients: set[web.WebSocketResponse] = set()
stats = {"frames": 0, "sent": 0, "bytes": 0, "tiles": 0}


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
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            d = msg.json()
            t = d.get("t")
            if t == "key":
                code = KEYS.get(str(d.get("k", "")).lower())
                if code:
                    LIB.core_key(code, bool(d.get("down")))
            elif t == "tap":
                code = KEYS.get(str(d.get("k", "")).lower())
                if code:
                    LIB.core_key(code, True)
                    await asyncio.sleep(0.06)
                    LIB.core_key(code, False)
            elif t == "keyframe":
                await send_keyframe(ws)
    finally:
        clients.discard(ws)
    return ws


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
    ])
    # on_startup handlers are awaited, so the pump has to be detached as a task
    # rather than returned, or startup blocks on a loop that never ends.
    async def _spawn_pump(a):
        a["pump"] = asyncio.create_task(pump())
    app.on_startup.append(_spawn_pump)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)


if __name__ == "__main__":
    main()
