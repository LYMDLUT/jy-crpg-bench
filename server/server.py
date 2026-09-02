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
import hashlib
import io
import json
import math
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
HOST = os.environ.get("QUNXIA_HOST", "0.0.0.0")
SEND_HZ = float(os.environ.get("QUNXIA_SEND_HZ", "20"))

LIB.core_set_option.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
LIB.core_init.argtypes = [ctypes.c_char_p] * 3
LIB.core_init.restype = ctypes.c_bool
LIB.core_key.argtypes = [ctypes.c_int, ctypes.c_bool]
LIB.core_fps.restype = ctypes.c_double
LIB.core_frame_serial.restype = ctypes.c_uint64
LIB.core_ticks.restype = ctypes.c_uint64
LIB.core_last_error.restype = ctypes.c_char_p
LIB.fb_encode_delta.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
LIB.fb_encode_delta.restype = ctypes.c_int
LIB.core_frame_hash.restype = ctypes.c_uint64
LIB.core_reset.restype = None
LIB.fb_reset.restype = None
LIB.fb_snapshot.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
LIB.fb_snapshot.restype = ctypes.c_int
LIB.core_release_all_keys.restype = None
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
# Created by the startup hook inside aiohttp's running loop. Constructing an
# asyncio.Lock at import time binds it to a different loop on Python 3.9 as
# soon as contention occurs.
api_lock = None               # one action at a time; the game is single-player
paused = threading.Event()    # held while the core is rebooted, so retro_reset
                              # is never called underneath a running retro_run
paused_ack = threading.Event()

clients: set[web.WebSocketResponse] = set()
stats = {"frames": 0, "sent": 0, "bytes": 0, "tiles": 0, "dropped": 0,
         "pump_errors": 0, "last_error": "", "pump_ticks": 0, "pump_stage": "init",
         "queued": 0}
SEND_TIMEOUT = float(os.environ.get("QUNXIA_SEND_TIMEOUT", "3"))
# Recording. Tile deltas are what the stream already produces, so a recording is
# just those kept with timestamps, plus the keys that caused them.
IDLE_AFTER = 3.0          # no action for this long and the tail is idle
IDLE_TAIL = 30.0          # of which only the last this much is kept
KEYFRAME_EVERY = 30.0     # so pruning can always start from a whole picture
REC_MAX_BYTES = 12 << 20
LOCK_TIMEOUT = float(os.environ.get("QUNXIA_LOCK_TIMEOUT", "30"))
# Four frames can fit inside one slow game-loop redraw, so a short keydown and
# keyup may be consumed together without producing a map step. Ten frames are
# still well below the game's held-key repeat delay, but reliably span a loop
# iteration. Measure all tap phases against emulated frames rather than wall
# time so host scheduling cannot shorten a pulse.
DEFAULT_TAP_FRAMES = 10
KEY_RELEASE_FRAMES = 2
BETWEEN_TAPS_FRAMES = 6
MAX_HOLD_FRAMES = 1200
MAX_GAP_FRAMES = 600
MAX_KEYS_PER_ACTION = 100
MAX_ACTION_FRAMES = 2800
MAX_WAIT_MS = 60000
MAX_HISTORY_LIMIT = 300
# Reset restores this rather than rebooting. It puts the agent in the opening
# room with a character already made, because creating one means driving the
# 注音 IME, which is a puzzle about input methods and not about the game.
START_STATE = os.environ.get("QUNXIA_START_STATE", str(ROOT.parent / "saves" / "start.state"))
RESUME_STATE = os.environ.get("QUNXIA_RESUME_STATE", "")
AUTOSAVE_SECONDS = float(os.environ.get("QUNXIA_AUTOSAVE_SECONDS", "0"))
STATE_DIR = os.environ.get("QUNXIA_STATE_DIR", str(pathlib.Path(SAVES) / "states"))
RECORDING_FILE = os.environ.get("QUNXIA_RECORDING", "")
RECORDING_FLUSH_SECONDS = float(os.environ.get("QUNXIA_RECORDING_FLUSH_SECONDS", "0.5"))

# Everything anyone does to this session, so the page can show who is doing
# what. The game is shared, so this doubles as "why did the screen just move".
history: collections.deque = collections.deque(maxlen=300)
_seq = [0]
# Counted per game, so a reset starts a fresh session rather than continuing one.
session = {"started": time.time(), "actions": 0, "by_api": 0, "by_web": 0}
agents: collections.Counter = collections.Counter()
rec: dict = {"started": time.time(), "events": [], "bytes": 0, "last_key": 0.0,
             "last_activity": time.time(), "actor": ""}
recording_pending: collections.deque = collections.deque()
recording_writer_task = None
recording_flush_lock = None
recording_file_lock = threading.Lock()
recording_resetting = False
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
    if verb in ("KEY", "KEYS", "TEXT", "WAIT"):
        rec_note_activity()
        session["actions"] += 1
        session["by_web" if src == "web" else "by_api"] += 1
        agents[src] += 1
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
        send = ws.send_str(data) if text else ws.send_bytes(data)
        await asyncio.wait_for(send, timeout=SEND_TIMEOUT)
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
    await fanout(json.dumps({"t": "log", "e": [entry], "s": session_summary()}), text=True)


def emulate():
    """Own thread. ctypes drops the GIL for each call, so asyncio keeps running."""
    budget = 1.0 / max(1.0, LIB.core_fps())
    nxt = time.perf_counter()
    while True:
        if paused.is_set():
            paused_ack.set()
            time.sleep(0.02)
            nxt = time.perf_counter()
            continue
        paused_ack.clear()
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
    last_key_at = 0.0
    while True:
        try:
            await asyncio.sleep(period)
            stats["pump_ticks"] += 1
            now = time.time()
            # A whole picture at intervals, so a pruned recording always has
            # somewhere to start replaying from.
            force = now - last_key_at >= KEYFRAME_EVERY
            serial = LIB.core_frame_serial()
            if serial == last_serial and not force:
                continue
            last_serial = serial
            stats["pump_stage"] = "encode"
            n = LIB.fb_encode_delta(BUF, len(BUF), 1 if force else 0)
            if n <= 0:
                continue
            count = int.from_bytes(BUF.raw[11:13], "little")
            if count == 0 and not force:
                continue
            if force:
                last_key_at = now
            stats["pump_stage"] = "compress"
            payload = zlib.compress(BUF.raw[:n], 6)
            rec_add("f", payload, keyframe=force)
            if not clients:
                stats["pump_stage"] = "idle"
                continue
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


def rec_note_activity():
    rec["last_activity"] = time.time()


def rec_add(kind, payload=None, key=None, down=None, keyframe=False):
    if recording_resetting:
        return
    now = time.time()
    ev = {"t": round(now - rec["started"], 3)}
    if kind == "f":
        ev["d"] = base64.b64encode(payload).decode()
        if keyframe:
            ev["k"] = 1
        rec["bytes"] += len(payload)
    else:
        ev["key"] = key
        ev["down"] = bool(down)
        if rec["actor"]:
            ev["who"] = rec["actor"]
    rec["events"].append(ev)
    if RECORDING_FILE:
        recording_pending.append(dict(ev))
    rec_prune(now)


def _recording_bytes(events):
    """Approximate the compressed payload bytes represented by ``events``."""
    return sum(len(e.get("d", "")) * 3 // 4 for e in events)


def _recording_path():
    return pathlib.Path(RECORDING_FILE) if RECORDING_FILE else None


def _write_recording_header():
    path = _recording_path()
    if path is None:
        return
    with recording_file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "started": rec["started"]}) + "\n",
                        encoding="utf-8")


def load_persisted_recording():
    """Restore the full per-user recording before the pump starts."""
    path = _recording_path()
    if path is None or not path.is_file():
        if path is not None:
            _write_recording_header()
        return
    try:
        with path.open("r", encoding="utf-8") as stream:
            header = json.loads(stream.readline() or "{}")
            started = float(header.get("started", rec["started"]))
            events = []
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # A crash can leave only the final append incomplete. Keep
                    # all complete events before that line.
                    break
                if isinstance(event, dict) and "t" in event:
                    events.append(event)
        rec.update(started=started, events=events,
                   bytes=_recording_bytes(events), last_activity=time.time(), actor="")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # A partially written journal should not prevent the game from booting.
        rec.update(events=[], bytes=0)
        _write_recording_header()


def _append_recording_batch(batch):
    path = _recording_path()
    if path is None or not batch:
        return
    with recording_file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for event in batch:
                stream.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
            stream.flush()


def recording_lock():
    global recording_flush_lock
    if recording_flush_lock is None:
        recording_flush_lock = asyncio.Lock()
    return recording_flush_lock


async def flush_recording():
    if not RECORDING_FILE:
        return
    async with recording_lock():
        if not recording_pending:
            return
        batch = list(recording_pending)
        recording_pending.clear()
        try:
            await asyncio.to_thread(_append_recording_batch, batch)
        except Exception:
            recording_pending.extendleft(reversed(batch))
            raise


async def recording_writer():
    """Batch journal writes so frame encoding never waits on disk I/O."""
    try:
        while True:
            await asyncio.sleep(max(0.05, RECORDING_FLUSH_SECONDS))
            try:
                await flush_recording()
            except Exception as exc:
                stats["last_error"] = f"recording: {type(exc).__name__}: {exc}"
    except asyncio.CancelledError:
        await flush_recording()
        raise


def _first_keyframe(events):
    return next((i for i, e in enumerate(events)
                 if e.get("k") and e.get("d")), None)


def recording_events():
    """Return a replayable recording with a zero-based local timeline.

    Idle and byte pruning can leave the retained events starting many hours
    after the session began.  Replaying those original timestamps makes the
    browser wait for the old session uptime before showing the first frame.
    Start at the first retained keyframe and rebase timestamps so playback and
    export describe the retained recording, not the discarded prefix.
    """
    events = list(rec["events"])
    if not events:
        return []
    start = _first_keyframe(events)
    if start is None:
        start = next((i for i, e in enumerate(events) if e.get("d")), 0)
    events = events[start:]
    try:
        base = float(events[0].get("t", 0))
    except (TypeError, ValueError):
        base = 0.0
    out = []
    for event in events:
        item = dict(event)
        try:
            timestamp = float(item.get("t", 0))
        except (TypeError, ValueError):
            timestamp = base
        item["t"] = round(max(0.0, timestamp - base), 3)
        out.append(item)
    return out


def rec_prune(now):
    """Two bounds. A long idle tail keeps only its last IDLE_TAIL seconds, so an
    untouched game does not grow forever while still showing its own animation.
    And the whole thing is capped, dropping from the front to the oldest
    keyframe that fits, because deltas cannot be replayed from the middle."""
    # Multi-user sessions opt into the disk journal so their replay can span
    # browser and backend restarts. Keep that full history in memory as well;
    # the bounded in-memory mode remains the default for standalone runs.
    if RECORDING_FILE:
        return
    idle_for = now - rec["last_activity"]
    if idle_for > IDLE_AFTER:
        cutoff = round(now - rec["started"] - IDLE_TAIL, 3)
        head, tail = [], []
        for ev in rec["events"]:
            (tail if ev["t"] >= cutoff else head).append(ev)
        # only trailing idle frames are droppable; anything before the idle
        # stretch began is real history
        idle_began = round(now - rec["started"] - idle_for, 3)
        keep = [e for e in head if e["t"] <= idle_began] + tail
        if len(keep) < len(rec["events"]):
            rec["events"] = keep
            rec["bytes"] = _recording_bytes(keep)

    if rec["bytes"] > REC_MAX_BYTES:
        events = rec["events"]
        start = _first_keyframe(events)
        while start is not None and _recording_bytes(events[start:]) > REC_MAX_BYTES:
            next_start = next((i for i in range(start + 1, len(events))
                               if events[i].get("k") and events[i].get("d")), None)
            if next_start is None:
                break
            start = next_start
        if start is not None and start > 0:
            rec["events"] = events[start:]
            rec["bytes"] = _recording_bytes(rec["events"])


async def rec_reset():
    global recording_resetting
    recording_resetting = True
    try:
        if RECORDING_FILE:
            async with recording_lock():
                recording_pending.clear()
                rec.update(started=time.time(), events=[], bytes=0, last_key=0.0,
                           last_activity=time.time())
                _write_recording_header()
        else:
            recording_pending.clear()
            rec.update(started=time.time(), events=[], bytes=0, last_key=0.0,
                       last_activity=time.time())
    finally:
        recording_resetting = False


def session_summary():
    return {"started_at": session["started"],
            "uptime_s": round(time.time() - session["started"], 1),
            "actions": session["actions"],
            "by_api": session["by_api"], "by_web": session["by_web"],
            "agents": dict(agents.most_common(8))}


async def reap():
    """Drop clients that closed without a handshake. Without this they linger,
    are counted, and are sent every frame."""
    while True:
        await asyncio.sleep(15)
        for ws in list(clients):
            if ws.closed:
                clients.discard(ws)


async def save_resume_state():
    """Persist the live multi-user session without racing the emulator thread."""
    if not RESUME_STATE or not await acquire_action_lock():
        return False
    try:
        await pause_emulator()
        try:
            LIB.core_release_all_keys()
            os.makedirs(os.path.dirname(RESUME_STATE) or ".", exist_ok=True)
            return bool(LIB.core_save_state(RESUME_STATE.encode()))
        finally:
            resume_emulator()
    finally:
        action_lock().release()


async def autosave_resume():
    while True:
        await asyncio.sleep(AUTOSAVE_SECONDS)
        try:
            await save_resume_state()
        except Exception as exc:
            stats["last_error"] = f"autosave: {exc}"


async def send_keyframe(ws):
    n = LIB.fb_encode_delta(BUF, len(BUF), 1)
    if n > 0:
        await ws.send_bytes(zlib.compress(BUF.raw[:n], 6))


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await ws.prepare(request)
    clients.add(ws)
    await send_keyframe(ws)
    await ws.send_str(json.dumps({"t": "log", "e": list(history)[-80:],
                                  "s": session_summary()}))
    # code -> (name, core tick at keydown). Browser automation can emit keydown
    # and keyup within one emulated frame, so remember when each press reached
    # the core and fence short pulses on release.
    holding: dict[int, tuple[str, int]] = {}
    lock_held = False
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
                    if down and code not in holding:
                        if not lock_held:
                            lock_held = await acquire_action_lock()
                        if not lock_held:
                            log_action("web", "KEY", name, detail="busy", ok=False)
                            continue
                        try:
                            rec["actor"] = "web"
                            if await press_web_key(name, code, holding):
                                log_action("web", "KEY", name)
                        except BaseException:
                            if not holding and lock_held:
                                action_lock().release()
                                lock_held = False
                            raise
                    elif not down:
                        rec["actor"] = "web"
                        await release_web_key(name, code, holding)
                        if not holding and lock_held:
                            action_lock().release()
                            lock_held = False
            elif t == "tap":
                name = str(d.get("k", "")).lower()
                code = KEYS.get(name)
                if code and code not in holding:
                    borrowed = lock_held
                    if borrowed or await acquire_action_lock():
                        try:
                            rec["actor"] = "web"
                            log_action("web", "KEY", name)
                            await tap(code, DEFAULT_TAP_FRAMES, name)
                        finally:
                            if not borrowed:
                                action_lock().release()
                    else:
                        log_action("web", "KEY", name, detail="busy", ok=False)
            elif t == "keyframe":
                await send_keyframe(ws)
    finally:
        for code, (name, _) in list(holding.items()):
            LIB.core_key(code, False)
            key_event(name, False)
        holding.clear()
        if lock_held:
            action_lock().release()
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


async def wait_core_frames(frames):
    """Wait until the emulator has actually completed ``frames`` frames."""
    frames = max(1, int(frames))
    fps = max(1.0, LIB.core_fps())
    target = LIB.core_ticks() + frames
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(1.0, frames / fps * 5 + 0.5)
    poll = min(0.01, 0.5 / fps)
    while LIB.core_ticks() < target:
        if loop.time() >= deadline:
            raise RuntimeError("emulator frame clock stalled during input")
        await asyncio.sleep(poll)


async def pause_emulator():
    """Stop between emulated frames before calling reset/serialize APIs."""
    paused.set()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 2.0
    while not paused_ack.is_set():
        if loop.time() >= deadline:
            paused.clear()
            raise RuntimeError("emulator did not pause")
        await asyncio.sleep(0.005)


def resume_emulator():
    paused.clear()
    # Do not let a following pause observe the acknowledgement from this one.
    paused_ack.clear()


async def acquire_action_lock():
    """Acquire the one-player lease shared by REST and browser input."""
    stats["queued"] += 1
    try:
        await asyncio.wait_for(action_lock().acquire(), timeout=LOCK_TIMEOUT)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        stats["queued"] -= 1


def action_lock():
    if api_lock is None:
        raise RuntimeError("action lock is not initialized")
    return api_lock


async def press_web_key(name, code, holding):
    """Press a browser key once and remember the core tick it reached."""
    if code in holding:
        return False
    LIB.core_key(code, True)
    holding[code] = (name, LIB.core_ticks())
    key_event(name, True)
    return True


async def release_web_key(name, code, holding):
    """Release a browser key after it has spanned enough emulated frames.

    Human holds that already exceed the minimum stop immediately. Very short
    taps are extended only to ``DEFAULT_TAP_FRAMES`` and followed by the normal
    release fence, making automated browser keypresses as reliable as the REST
    API without changing long-hold behaviour.
    """
    pressed = holding.get(code)
    if pressed is None:
        return False
    pressed_name, pressed_at = pressed
    elapsed = max(0, LIB.core_ticks() - pressed_at)
    remaining = max(0, DEFAULT_TAP_FRAMES - elapsed)
    try:
        if remaining:
            await wait_core_frames(remaining)
    finally:
        # Cancellation or a dropped socket must never strand a movement key.
        LIB.core_key(code, False)
        holding.pop(code, None)
        key_event(pressed_name or name, False)
    await wait_core_frames(KEY_RELEASE_FRAMES)
    return True


def key_event(name, down):
    """Tell browsers a key is physically down, so a held key stays lit for as
    long as it is held instead of blinking once when the action finishes."""
    if name:
        rec_add("k", key=name, down=down)
        asyncio.create_task(fanout(json.dumps({"t": "key", "k": name, "down": down}),
                                   text=True))


async def tap(code, hold_frames, name=None):
    key_event(name, True)
    LIB.core_key(code, True)
    try:
        await wait_core_frames(hold_frames)
    finally:
        LIB.core_key(code, False)
        key_event(name, False)
    await wait_core_frames(KEY_RELEASE_FRAMES)


def held_note(steps):
    """Longest single press in this action, in seconds, when worth showing."""
    fps = max(1.0, LIB.core_fps())
    longest = max((v for k, v, *_ in steps if k not in ("wait", "frames")), default=0) / fps
    return f"{longest:.1f}s" if longest >= 0.25 else ""


async def run_action(request, steps, note, verb="KEY"):
    """Steps are key taps, ``("wait", seconds)`` or ``("frames", count)``.

    By default it does not return a screenshot. Encoding a PNG for every
    keypress cost real CPU on a shared-core box and most were never read. With
    ``?image=1`` the settled frame is captured before this action releases its
    lease, so the observation cannot belong to another controller.

    One action runs at a time so the game stays coherent when several agents
    act on it, but a caller waiting behind others is told so instead of being
    left to hang.
    """
    try:
        settle_args = settle_options(request)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    if not await acquire_action_lock():
        return web.json_response(
            {"ok": False, "error": "busy", "queued": stats["queued"],
             "hint": "another agent holds the game; retry"}, status=503)

    image = None
    image_w = image_h = 0
    image_mime = ""
    image_error = ""
    try:
        # Logged before the keys are sent, not after: the panel should show an
        # action starting, not report it once it is already over.
        rec["actor"] = actor(request)
        log_action(rec["actor"], verb, note, detail=held_note(steps))
        baseline = LIB.core_frame_hash()
        for step in steps:
            kind, val = step[0], step[1]
            if kind == "wait":
                await asyncio.sleep(val)
            elif kind == "frames":
                await wait_core_frames(val)
            else:
                await tap(kind, val, step[2] if len(step) > 2 else None)
        waited, changed = await settle(baseline, **settle_args)
        if wants_image(request):
            try:
                image, image_w, image_h, image_mime = snapshot("png")
                if not image:
                    image_error = "no frame"
            except Exception as exc:
                image_error = f"{type(exc).__name__}: {exc}"
    finally:
        action_lock().release()

    result = {
        "ok": True, "action": note, "changed": changed,
        "width": LIB.core_width(), "height": LIB.core_height(),
        "frame": LIB.core_frame_serial(), "settled_frames": waited,
    }
    if image:
        result.update({
            "image_width": image_w, "image_height": image_h,
            "image": f"data:{image_mime};base64," + base64.b64encode(image).decode(),
        })
    if image_error:
        result["image_error"] = image_error
    return web.json_response(result)


async def body_of(request):
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def bounded_int(value, name, default, minimum, maximum):
    """Parse an integer without silently accepting fractions or booleans."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{name} must be an integer")
        value = int(value)
    elif not isinstance(value, int):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def settle_options(request):
    """Validated headless equivalents of the native API settle controls."""
    q = request.query
    react = bounded_int(q.get("react"), "react", 30, 0, 2000)
    stable = bounded_int(q.get("stable"), "stable", 9, 1, 600)
    maxframes = bounded_int(q.get("maxsettle"), "maxsettle", 120, 1, 2000)
    return {"react": react, "stable": stable, "maxframes": max(maxframes, react)}


def wants_image(request):
    return str(request.query.get("image", "0")).lower() in ("1", "true", "yes")


def validate_action_frames(count, hold, gap):
    total = count * (hold + KEY_RELEASE_FRAMES) + max(0, count - 1) * gap
    if total > MAX_ACTION_FRAMES:
        raise ValueError(
            f"action is too long ({total} frames; maximum {MAX_ACTION_FRAMES})"
        )


def keycode(name):
    return KEYS.get(str(name).strip().lower())


def state_path(body):
    raw = body.get("name")
    if raw is None:
        slot = bounded_int(body.get("slot"), "slot", 1, 1, 99)
        raw = f"slot{slot}"
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("state name must be a non-empty string")
    clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw.strip())[:64]
    if not clean or clean in (".", ".."):
        raise ValueError("invalid state name")
    return pathlib.Path(STATE_DIR) / f"{clean}.state", clean


def attach_snapshot(result):
    data, w, h, mime = snapshot("png")
    if data:
        result.update({
            "width": LIB.core_width(), "height": LIB.core_height(),
            "frame": LIB.core_frame_serial(),
            "image_width": w, "image_height": h,
            "image": f"data:{mime};base64," + base64.b64encode(data).decode(),
        })
    else:
        result["image_error"] = "no frame"
    return result


def core_error(fallback):
    try:
        raw = LIB.core_last_error()
        if raw:
            return raw.decode(errors="replace")
    except Exception:
        pass
    return fallback


# Readable stand-in names, in the register of the game, so an agent that did
# not introduce itself is still something you can point at in the log.
_ADJ = ("swift", "jade", "iron", "azure", "silent", "crimson", "golden", "misty",
        "lone", "wandering", "ancient", "white", "shadow", "drunken", "nine", "cloud")
_NOUN = ("crane", "tiger", "dragon", "sparrow", "blade", "monk", "fox", "phoenix",
         "serpent", "willow", "peak", "lotus", "sabre", "pilgrim", "heron", "bell")


def anon_name(seed: str) -> str:
    h = hashlib.blake2s(seed.encode(), digest_size=4).digest()
    return f"{_ADJ[h[0] % len(_ADJ)]}-{_NOUN[h[1] % len(_NOUN)]}-{h[2]:02x}"


def actor(request):
    """Who is acting.

    An agent should name itself with an X-Agent header. When it does not, fall
    back to a short stable id derived from its address and client string, so
    two anonymous agents are still told apart instead of both showing as "api".
    """
    given = request.headers.get("X-Agent") or request.query.get("agent")
    if given:
        clean = "".join(c for c in given if c.isalnum() or c in "-_.")[:16]
        if clean:
            return clean
    peer = request.remote or "?"
    ua = request.headers.get("User-Agent", "")
    return anon_name(f"{peer}|{ua}")


async def api_key(request):
    d = await body_of(request)
    if d is None:
        return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
    code = keycode(d.get("key", ""))
    if not code:
        return web.json_response({"ok": False, "error": "unknown key"}, status=400)
    try:
        hold = bounded_int(d.get("hold"), "hold", DEFAULT_TAP_FRAMES,
                           1, MAX_HOLD_FRAMES)
        times = bounded_int(d.get("times"), "times", 1,
                            1, MAX_KEYS_PER_ACTION)
        gap = bounded_int(d.get("gap"), "gap", BETWEEN_TAPS_FRAMES,
                          0, MAX_GAP_FRAMES)
        validate_action_frames(times, hold, gap)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    name = str(d.get("key")).strip().lower()
    steps = []
    for i in range(times):
        steps.append((code, hold, name))
        if i != times - 1 and gap:
            steps.append(("frames", gap))
    return await run_action(request, steps, name + (f" x{times}" if times > 1 else ""))


async def api_keys(request):
    d = await body_of(request)
    if d is None:
        return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
    names = d.get("keys") or []
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_KEYS_PER_ACTION:
        return web.json_response(
            {"ok": False,
             "error": f"keys must contain between 1 and {MAX_KEYS_PER_ACTION} entries"},
            status=400,
        )
    codes = [keycode(k) for k in names]
    if any(c is None for c in codes):
        return web.json_response({"ok": False, "error": "unknown key in list"}, status=400)
    try:
        hold = bounded_int(d.get("hold"), "hold", DEFAULT_TAP_FRAMES,
                           1, MAX_HOLD_FRAMES)
        gap = bounded_int(d.get("gap"), "gap", BETWEEN_TAPS_FRAMES,
                          0, MAX_GAP_FRAMES)
        validate_action_frames(len(names), hold, gap)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    steps = []
    for i, c in enumerate(codes):
        steps.append((c, hold, str(names[i]).strip().lower()))
        if i != len(codes) - 1 and gap:
            steps.append(("frames", gap))
    return await run_action(request, steps, " ".join(map(str, names)), verb="KEYS")


async def api_wait(request):
    d = await body_of(request)
    if d is None:
        return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
    try:
        ms = bounded_int(d.get("ms"), "ms", 1000, 0, MAX_WAIT_MS)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    return await run_action(request, [("wait", ms / 1000)], f"{ms}ms", verb="WAIT")


async def api_screen(request):
    """Look without acting. JSON, or ``?format=png|webp`` for raw bytes."""
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


async def api_key_names(_request):
    return web.json_response({"keys": sorted(KEYS)})


async def api_slots(_request):
    root = pathlib.Path(STATE_DIR)
    slots = []
    if root.exists():
        for path in sorted(root.glob("*.state")):
            try:
                stat = path.stat()
            except OSError:
                continue
            slots.append({
                "name": path.stem, "bytes": stat.st_size,
                "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            })
    return web.json_response({"slots": slots})


async def api_save(request):
    body = await body_of(request)
    if body is None:
        return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
    try:
        path, name = state_path(body)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    if not await acquire_action_lock():
        return web.json_response({"ok": False, "error": "busy"}, status=503)
    ok = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        await pause_emulator()
        try:
            LIB.core_release_all_keys()
            ok = bool(LIB.core_save_state(str(path).encode()))
            result = {"ok": ok, "slot": name}
            if not ok:
                result["error"] = core_error("save failed")
            if wants_image(request):
                try:
                    attach_snapshot(result)
                except Exception as exc:
                    result["image_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            resume_emulator()
    except Exception as exc:
        result = {"ok": False, "slot": name, "error": str(exc)}
    finally:
        action_lock().release()
    log_action(actor(request), "SAVE", name, ok=ok)
    return web.json_response(result, status=200 if result.get("ok") else 500)


async def api_load(request):
    body = await body_of(request)
    if body is None:
        return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
    try:
        path, name = state_path(body)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    if not path.is_file():
        return web.json_response({"ok": False, "error": "no such slot"}, status=404)
    if not await acquire_action_lock():
        return web.json_response({"ok": False, "error": "busy"}, status=503)
    ok = False
    try:
        await pause_emulator()
        try:
            LIB.core_release_all_keys()
            ok = bool(LIB.core_load_state(str(path).encode()))
            if ok:
                LIB.fb_reset()
        finally:
            resume_emulator()
        if ok:
            await wait_core_frames(2)
        result = {"ok": ok, "slot": name}
        if not ok:
            result["error"] = core_error("load failed")
        if wants_image(request):
            try:
                attach_snapshot(result)
            except Exception as exc:
                result["image_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result = {"ok": False, "slot": name, "error": str(exc)}
    finally:
        action_lock().release()
    log_action(actor(request), "LOAD", name, ok=ok)
    if ok:
        await fanout(json.dumps({"t": "clear"}), text=True)
        for ws in list(clients):
            try:
                await asyncio.wait_for(send_keyframe(ws), timeout=SEND_TIMEOUT)
            except Exception:
                clients.discard(ws)
    return web.json_response(result, status=200 if result.get("ok") else 500)


async def api_reset(request):
    """Hidden. Reboots the emulated machine back to the title screen and wipes
    the activity log. Unlisted in /api/help and 404s unless the token matches,
    so a visitor who stumbles on the path cannot wipe someone's game."""
    want = os.environ.get("QUNXIA_RESET_TOKEN")
    got = request.query.get("token") or request.headers.get("X-Reset-Token")
    if not want or got != want:
        raise web.HTTPNotFound()

    restored = False
    async with action_lock():
        await pause_emulator()
        try:
            LIB.core_release_all_keys()
            if os.path.exists(START_STATE):
                restored = bool(LIB.core_load_state(START_STATE.encode()))
            if not restored:
                LIB.core_reset()           # no start state, fall back to a reboot
            LIB.fb_reset()
        finally:
            resume_emulator()
        history.clear()
        _seq[0] = 0
        session.update(started=time.time(), actions=0, by_api=0, by_web=0)
        agents.clear()
        await rec_reset()
        await asyncio.sleep(0.4 if restored else 1.5)

    await fanout(json.dumps({"t": "clear"}), text=True)
    for ws in list(clients):
        try:
            await asyncio.wait_for(send_keyframe(ws), timeout=SEND_TIMEOUT)
        except Exception:
            clients.discard(ws)
    log_action("api", "RESET", "restored start state" if restored else "rebooted to title")
    return web.json_response({"ok": True, "reset": True, "restored": restored})


async def api_snapshot(request):
    """Hidden. Writes the current position as the state /api/reset restores."""
    want = os.environ.get("QUNXIA_RESET_TOKEN")
    got = request.query.get("token") or request.headers.get("X-Reset-Token")
    if not want or got != want:
        raise web.HTTPNotFound()
    async with action_lock():
        await pause_emulator()
        try:
            os.makedirs(os.path.dirname(START_STATE), exist_ok=True)
            LIB.core_release_all_keys()
            ok = bool(LIB.core_save_state(START_STATE.encode()))
        finally:
            resume_emulator()
    size = os.path.getsize(START_STATE) if ok and os.path.exists(START_STATE) else 0
    log_action("api", "RESET", "saved start state" if ok else "start state failed", ok=ok)
    return web.json_response({"ok": ok, "path": START_STATE, "bytes": size})


async def api_recording(_request):
    """The session so far as tile deltas and key presses, for playback."""
    await flush_recording()
    events = recording_events()
    return web.json_response({
        "started": rec["started"],
        "duration": round(events[-1]["t"] if events else 0, 2),
        "events": events,
        "bytes": rec["bytes"],
    })


async def api_history(request):
    try:
        limit = bounded_int(request.query.get("limit"), "limit", 100,
                            0, MAX_HISTORY_LIMIT)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    items = list(history)
    return web.json_response({"history": items[-limit:] if limit else []})


async def api_help(request):
    # Not logged: the page fetches this on every load to fill the copy box, so
    # logging it fills the panel with entries nobody performed.
    lang = request.query.get("lang", "en")
    core_only = request.query.get("part") == "core"
    return web.Response(text=system_prompt(base_url(request), lang, core_only),
                        content_type="text/plain", charset="utf-8")


async def index(_request):
    return web.FileResponse(ROOT / "index.html")


async def status(_request):
    return web.json_response({
        "width": LIB.core_width(), "height": LIB.core_height(),
        "fps": round(LIB.core_fps(), 3), "frame": LIB.core_frame_serial(),
        "clients": len(clients), "session": session_summary(), **stats,
    })


async def startup(app):
    global api_lock, recording_writer_task, recording_flush_lock
    api_lock = asyncio.Lock()
    recording_flush_lock = asyncio.Lock()
    load_persisted_recording()
    app["pump"] = asyncio.create_task(pump())
    app["reaper"] = asyncio.create_task(reap())
    if RECORDING_FILE:
        recording_writer_task = asyncio.create_task(recording_writer())
        app["recording_writer"] = recording_writer_task
    if RESUME_STATE and AUTOSAVE_SECONDS > 0:
        app["autosave"] = asyncio.create_task(autosave_resume())


async def cleanup(app):
    tasks = []
    for name in ("pump", "reaper", "autosave", "recording_writer"):
        task = app.get(name)
        if task:
            task.cancel()
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await flush_recording()
    if RESUME_STATE:
        try:
            await save_resume_state()
        except Exception as exc:
            stats["last_error"] = f"shutdown autosave: {exc}"


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
    if RESUME_STATE and os.path.exists(RESUME_STATE):
        if not LIB.core_load_state(RESUME_STATE.encode()):
            print("resume state failed: " + LIB.core_last_error().decode(), file=sys.stderr)
        else:
            LIB.fb_reset()
    threading.Thread(target=emulate, daemon=True).start()

    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/ws", ws_handler),
        web.get("/status", status),
        web.get("/api/screen", api_screen),
        web.get("/api/help", api_help),
        web.get("/api/keys", api_key_names),
        web.get("/api/slots", api_slots),
        web.get("/api/history", api_history),
        web.get("/api/recording", api_recording),
        web.post("/api/reset", api_reset),
        web.post("/api/snapshot", api_snapshot),
        web.post("/api/key", api_key),
        web.post("/api/keys", api_keys),
        web.post("/api/wait", api_wait),
        web.post("/api/save", api_save),
        web.post("/api/load", api_load),
    ])
    # Startup handlers are awaited, so the workers are detached tasks rather
    # than returned, or startup would block on loops that never end.
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    web.run_app(app, host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
