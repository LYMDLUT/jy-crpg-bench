"""A model's walk on the world map, read from its replay and placed on the
rendered world map of worldmap.py.

    python worldmap_route.py <session id> [<minutes>]

Every frame from the first black frame of the replay (the crossing) to the
given minute of play, 60 by default, is placed on worldmap.png at the offset
of highest normalised cross-correlation, over the frame without the status
strip and without any dialogue box or menu. The world map always scrolls to
keep the hero at one screen position, so his tile is the offset of the frame
plus HERO, the screen point that the compass reading of a replay fixes. A
match is searched within MAX_JUMP px of the last placed frame and, when that
fails (after a scene or a loaded save), over the whole map at a quarter of the
resolution, where a match must reach GLOBAL_NCC. Frames inside a scene, a fight or a menu do not match the map and
are skipped. The output, routes/world-<session>.json, holds one row per placed
frame: map pixel x and y, the game coordinates, the minute of play and the
correlation.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "human"))
import field  # noqa: E402
import read_video as RV  # noqa: E402
from anchored_route import dialogue_mask, fps_of, frames, masked_ncc_map  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
W0, H0 = 320, 200
HERO = (145, 117)          # the hero tile centre on screen: frame offset + HERO is his tile on worldmap.png
MIN_NCC = 0.6
GLOBAL_NCC = 0.8          # a relocation over the whole map must match better: scene floors match the map at 0.6
MAX_JUMP = 160
K = 4                      # the reduction of the global search
OUT = os.path.join(HERE, "routes")


def coords(px, py, meta):
    """Map pixel to the coordinates the compass shows."""
    u = (px - meta["origin"][0]) / meta["tile"][0]
    v = (py - meta["origin"][1]) / meta["tile"][1]
    return round((v + u) / 2), round((v - u) / 2)


def track(video, t0, t1, speed):
    """The hero's tiles on the world map in a video from t0 to t1 seconds: one
    row (px, py, x, y, minute of play, correlation) per placed frame; speed is
    the replay speed, 1 for a recording in real time."""
    fps = fps_of(video)
    meta = json.load(open(os.path.join(HERE, "worldmap.json")))
    wm = np.asarray(Image.open(os.path.join(HERE, "worldmap.png")).convert("L"), np.float32)
    H, W = wm.shape
    small = wm[:H // K * K, :W // K * K].reshape(H // K, K, W // K, K).mean((1, 3))
    rows, last, last_f = [], None, None
    for i, f in enumerate(frames(video, t1)):
        if i / fps < t0:
            continue
        if last_f is not None and (np.abs(f.astype(np.int16) - last_f.astype(np.int16)).max(axis=2) > 30).sum() < 30:
            continue
        last_f = f
        g = f.astype(np.float32).mean(axis=2)
        keep = ~dialogue_mask(f)
        if keep.mean() < 0.6:
            continue
        hit = None
        if last is not None:
            x0, y0 = max(0, last[0] - MAX_JUMP), max(0, last[1] - MAX_JUMP)
            win = wm[y0:last[1] + H0 + MAX_JUMP, x0:last[0] + W0 + MAX_JUMP]
            m = masked_ncc_map(win, np.ones(win.shape, bool), g, keep)
            y, x = np.unravel_index(np.argmax(m), m.shape)
            if m[y, x] >= MIN_NCC:
                hit = (x0 + x, y0 + y, float(m[y, x]))
        if hit is None:
            gs = g[:H0 // K * K, :W0 // K * K].reshape(H0 // K, K, W0 // K, K).mean((1, 3))
            m = RV.ncc_map(small, gs)
            y, x = np.unravel_index(np.argmax(m), m.shape)
            if m[y, x] < MIN_NCC:
                continue
            X, Y = x * K, y * K
            x0, y0 = max(0, X - 2 * K), max(0, Y - 2 * K)
            win = wm[y0:Y + H0 + 2 * K, x0:X + W0 + 2 * K]
            m = masked_ncc_map(win, np.ones(win.shape, bool), g, keep)
            y, x = np.unravel_index(np.argmax(m), m.shape)
            if m[y, x] < GLOBAL_NCC:
                continue
            hit = (x0 + x, y0 + y, float(m[y, x]))
        last = hit[:2]
        px, py = hit[0] + HERO[0], hit[1] + HERO[1]
        cx, cy = coords(px, py, meta)
        rows.append([int(px), int(py), cx, cy, round(i / fps * speed / 60.0, 3), round(hit[2], 3)])
    return rows


def main():
    sid = sys.argv[1]
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    row = next(r for r in field.load_runs(dedup=False, keep_excluded=True) if r["id"] == sid)
    ev = json.load(open(os.path.join(HERE, "replay_events.json"), encoding="utf-8"))[sid]
    speed = json.load(open(os.path.join(HERE, "timelines", sid + ".json"), encoding="utf-8"))["speed"]
    video = os.path.join(HERE, "videos", sid + ".mp4")
    if not os.path.exists(video):
        import urllib.request
        os.makedirs(os.path.dirname(video), exist_ok=True)
        urllib.request.urlretrieve(row["video_url"], video)
    rows = track(video, ev["first_black_second"], minutes * 60 / speed, speed)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"world-{sid}.json")
    json.dump({"session": sid, "agent": row["agent"], "minutes": minutes,
               "columns": ["px", "py", "x", "y", "minute", "ncc"], "rows": rows}, open(out, "w"))
    print(sid, row["agent"], "placed", len(rows), "wrote", out)


if __name__ == "__main__":
    main()
