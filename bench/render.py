#!/usr/bin/env python3
"""Turn a session recording into an MP4.

The recording is the same tile deltas the browser stream uses, so rendering is
replaying them onto a canvas and piping raw frames to ffmpeg. Doing it here
rather than in a browser means a run can be finalised with nobody watching.
"""
import base64
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BAR = 32                 # strip under the game for the actor, action and keys
FPS = 20                 # output frame rate
# Native resolution. A benchmark run starts from a savestate already in the
# game, so the picture is 320x200 throughout; the 640x400 publisher intro only
# appears when booting from cold. Anything larger is scaled down to fit rather
# than the whole video being inflated to suit it.
GAME_W, GAME_H = 320, 200
GLYPH = {"up": "↗", "kp9": "↗", "upright": "↗", "ne": "↗",
         "down": "↙", "kp1": "↙", "downleft": "↙", "sw": "↙",
         "left": "↖", "kp7": "↖", "upleft": "↖", "nw": "↖",
         "right": "↘", "kp3": "↘", "downright": "↘", "se": "↘",
         "enter": "⏎", "space": "␣", "esc": "esc", "backspace": "⌫"}


def _font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/System/Library/Fonts/Menlo.ttc",
              "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def apply_delta(canvas, raw):
    """Paint one tile delta. Returns the canvas, reallocating on a mode change."""
    d = zlib.decompress(raw)
    _flags, w, h, tw, th, cols, _rows, count = struct.unpack_from("<BHHBBHHH", d, 0)
    if canvas is None or canvas.shape[1] != w or canvas.shape[0] != h:
        canvas = np.zeros((h, w, 3), np.uint8)
    idx_off, data_off = 13, 13 + count * 2
    tile_len = tw * th * 3
    for i in range(count):
        t = struct.unpack_from("<H", d, idx_off + i * 2)[0]
        x, y = (t % cols) * tw, (t // cols) * th
        src = np.frombuffer(d, np.uint8, tile_len, data_off + i * tile_len)
        src = src.reshape(th, tw, 3)
        ch, cw = min(th, h - y), min(tw, w - x)
        if ch > 0 and cw > 0:
            canvas[y:y + ch, x:x + cw] = src[:ch, :cw]
    return canvas


# A run can now be as long as a day. At a fixed 4x that would be a six hour
# video nobody watches and a render nobody waits for, so playback speeds up for
# long runs to keep the result bounded. Short runs are untouched.
MAX_VIDEO_SECONDS = float(os.environ.get("QUNXIA_MAX_VIDEO_SECONDS", "600"))


def render(recording, out_path, agent="", speed=4.0, width=960):
    events = recording.get("events") or []
    frames = [e for e in events if "d" in e]
    if not frames:
        raise ValueError("recording has no frames")

    # Start when the agent starts playing, not when the machine came up. The
    # gap between the two is the harness booting and the model reading its
    # brief, which is dead air on screen. Every delta before that point is
    # still applied to the canvas below, so the first rendered frame shows the
    # game as the agent found it rather than the black an earlier version had.
    acted = next((e["t"] for e in events
                  if e.get("act") is not None or e.get("key")), None)
    t_start = acted if acted is not None else frames[0]["t"]
    t_end = events[-1]["t"]
    span = t_end - t_start
    speed = max(speed, span / MAX_VIDEO_SECONDS)
    duration = max(0.2, span / speed)

    # A timeline of what happened and when, in video seconds. A few KB beside
    # a 1MB MP4, which is what makes the replay scrubbable without shipping the
    # 100MB+ recording to a browser.
    marks, held = [], {}
    for e in events:
        vt = round((e["t"] - t_start) / speed, 3)
        if vt < 0:
            continue
        if e.get("act") is not None:
            marks.append({"n": e["act"], "t": vt, "do": e.get("label", ""),
                          "keys": []})
        elif e.get("key"):
            if e.get("down"):
                held[e["key"]] = e["t"]
            else:
                down = held.pop(e["key"], None)
                if marks:
                    marks[-1]["keys"].append(
                        [e["key"], round((e["t"] - down) if down else 0, 3)])
    timeline = {"speed": round(speed, 3), "seconds": round(duration, 2),
                "size": [GAME_W, GAME_H + BAR], "bar": BAR, "marks": marks}

    canvas = None
    for e in events:
        if "d" in e:
            canvas = apply_delta(canvas, base64.b64decode(e["d"]))
            break

    out_w, out_h = GAME_W, GAME_H + BAR
    name_font, key_font = _font(10), _font(11)
    bar_cache, bar_key = None, None

    def bar_image(actor, act, clock, keys):
        img = Image.new("RGB", (out_w, BAR), (16, 16, 20))
        dr = ImageDraw.Draw(img)
        y = BAR // 2
        x = 6
        if actor:
            dr.text((x, y), actor, font=name_font, fill=(150, 190, 230), anchor="lm")
            x += int(dr.textlength(actor, font=name_font)) + 8
        stamp = f"#{act}" if act is not None else ""
        if stamp:
            dr.text((x, y), stamp, font=name_font, fill=(200, 170, 110), anchor="lm")
            x += int(dr.textlength(stamp, font=name_font)) + 8
        for k in keys[:4]:
            label = GLYPH.get(k, k)
            kw = int(dr.textlength(label, font=key_font)) + 8
            dr.rectangle([x, 6, x + kw, BAR - 6], fill=(30, 30, 38),
                         outline=(70, 90, 110))
            dr.text((x + kw // 2, y), label, font=key_font,
                    fill=(142, 205, 247), anchor="mm")
            x += kw + 4
        mm, ss = divmod(int(clock), 60)
        dr.text((out_w - 6, y), f"{mm}:{ss:02d}", font=name_font,
                fill=(120, 120, 132), anchor="rm")
        return np.asarray(img)

    def blit(dst, src):
        """Fit a frame of any mode into the native-sized game area."""
        h_, w_ = src.shape[0], src.shape[1]
        if w_ > GAME_W or h_ > GAME_H:                 # cold-boot 640x400
            step = max(1, -(-w_ // GAME_W), -(-h_ // GAME_H))
            src = src[::step, ::step]
            h_, w_ = src.shape[0], src.shape[1]
        oy, ox = (GAME_H - h_) // 2, (GAME_W - w_) // 2
        dst[:GAME_H] = 0
        dst[oy:oy + h_, ox:ox + w_] = src

    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}",
         "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE)

    down, actor, i, act = [], agent, 0, None
    total_frames = max(1, int(duration * FPS))
    frame = np.zeros((out_h, out_w, 3), np.uint8)
    try:
        for n in range(total_frames):
            now = t_start + (n / FPS) * speed
            while i < len(events) and events[i]["t"] <= now:
                e = events[i]
                i += 1
                if "d" in e:
                    canvas = apply_delta(canvas, base64.b64decode(e["d"]))
                elif e.get("act") is not None:
                    act = e["act"]
                    if e.get("who"):
                        actor = e["who"]
                elif e.get("key"):
                    if e.get("who"):
                        actor = e["who"]
                    if e.get("down"):
                        if e["key"] not in down:
                            down.append(e["key"])
                    elif e["key"] in down:
                        down.remove(e["key"])
            elapsed = int(now - t_start)
            key = (actor, act, elapsed, tuple(down))
            if key != bar_key:
                bar_cache, bar_key = bar_image(actor, act, elapsed, down), key
            blit(frame, canvas)
            frame[GAME_H:] = bar_cache
            ff.stdin.write(frame.tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
    return {"path": str(out_path), "seconds": round(duration, 1),
            "frames": total_frames, "size": f"{out_w}x{out_h}",
            "speed": round(speed, 3), "timeline": timeline}


if __name__ == "__main__":
    import sys
    rec = json.load(open(sys.argv[1]))
    print(render(rec, sys.argv[2], agent=sys.argv[3] if len(sys.argv) > 3 else ""))
