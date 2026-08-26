#!/usr/bin/env python3
"""Turn a session recording into an MP4.

The recording is the same tile deltas the browser stream uses, so rendering is
replaying them onto a canvas and piping raw frames to ffmpeg. Doing it here
rather than in a browser means a run can be finalised with nobody watching.
"""
import base64
import json
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BAR = 40                 # strip under the game for the actor and keys
FPS = 20                 # output frame rate
# The game switches between 320x200 and 640x400 mid session, so the video is
# drawn into a fixed area and each mode is scaled up to fit it. Sizing the
# output from the first frame broke the moment the mode changed.
GAME_W, GAME_H = 640, 400
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


def render(recording, out_path, agent="", speed=4.0, width=960):
    events = recording.get("events") or []
    frames = [e for e in events if "d" in e]
    if not frames:
        raise ValueError("recording has no frames")

    # Start at the first frame. Anything before it would encode as black, which
    # is what put a black lead-in on the front of every earlier export.
    t_start = frames[0]["t"]
    t_end = events[-1]["t"]
    duration = max(0.2, (t_end - t_start) / speed)

    canvas = None
    for e in events:
        if "d" in e:
            canvas = apply_delta(canvas, base64.b64decode(e["d"]))
            break

    out_w, out_h = GAME_W, GAME_H + BAR
    name_font, key_font = _font(15), _font(17)
    bar_cache, bar_key = None, None

    def bar_image(actor, keys):
        img = Image.new("RGB", (out_w, BAR), (16, 16, 20))
        dr = ImageDraw.Draw(img)
        x = 12
        if actor:
            dr.text((x, BAR // 2), actor, font=name_font, fill=(150, 190, 230), anchor="lm")
            x += int(dr.textlength(actor, font=name_font)) + 16
        for k in keys:
            label = GLYPH.get(k, k)
            tw_ = int(dr.textlength(label, font=key_font)) + 16
            dr.rounded_rectangle([x, 8, x + tw_, BAR - 8], 4,
                                 fill=(28, 28, 34), outline=(70, 90, 110))
            dr.text((x + tw_ // 2, BAR // 2), label, font=key_font,
                    fill=(142, 205, 247), anchor="mm")
            x += tw_ + 8
        return np.asarray(img)

    def blit(dst, src):
        """Scale a frame of either mode up into the fixed game area."""
        h_, w_ = src.shape[0], src.shape[1]
        f = max(1, min(GAME_W // w_, GAME_H // h_))
        up = np.repeat(np.repeat(src, f, 0), f, 1)
        oy, ox = (GAME_H - up.shape[0]) // 2, (GAME_W - up.shape[1]) // 2
        dst[:GAME_H] = 0
        dst[oy:oy + up.shape[0], ox:ox + up.shape[1]] = up

    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}",
         "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE)

    down, actor, i = [], agent, 0
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
                elif e.get("key"):
                    if e.get("who"):
                        actor = e["who"]
                    if e.get("down"):
                        if e["key"] not in down:
                            down.append(e["key"])
                    elif e["key"] in down:
                        down.remove(e["key"])
            key = (actor, tuple(down))
            if key != bar_key:
                bar_cache, bar_key = bar_image(actor, down), key
            blit(frame, canvas)
            frame[GAME_H:] = bar_cache
            ff.stdin.write(frame.tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
    return {"path": str(out_path), "seconds": round(duration, 1),
            "frames": total_frames, "size": f"{out_w}x{out_h}"}


if __name__ == "__main__":
    import sys
    rec = json.load(open(sys.argv[1]))
    print(render(rec, sys.argv[2], agent=sys.argv[3] if len(sys.argv) > 3 else ""))
