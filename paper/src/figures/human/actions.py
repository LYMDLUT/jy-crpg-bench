"""Measure every human capture the same way, and show what the threshold decides.

    python3 actions.py            # every session whose source is on disk

The action count of a human session is tile steps plus screen changes. The tile steps are
read off the isometric lattice and do not depend on how the capture was encoded: a step is
a shift of the scene by whole tiles and nothing else satisfies it. The screen changes are a
frame difference, and they do depend on the encode - a soft capture churns above a fixed
threshold of six while the player merely stands, so the same nine seconds of the opening
route reads 40 presses on one capture and 56 on another. So the threshold is taken from
each capture's own distribution of no-shift differences, in the gap between its churn and
its real repaints, as the panels are matched at each video's own gap. This prints both
counts side by side, and the churn itself, so the choice is visible rather than assumed.
"""
import json
import os
import subprocess
import sys

import numpy as np

import read_video as RV

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")


def prep(rec):
    """the 320-wide frame of the window the player was in the house, nothing more."""
    t0, t1 = rec["start_s"] - 1.0, rec["crossing_s"] + 1.0
    tag = f"{rec['id']}-w"
    out = os.path.join(WORK, f"{tag}.320.mp4")
    if os.path.exists(out):
        return tag
    src = os.path.join(WORK, f"{rec['id']}.mp4")
    if not os.path.exists(src):
        return None
    crop = rec.get("crop") or "-"
    if crop == "-":
        w, h = RV.native_size(src)
        crop = f"{w}:{h}:0:0"
    w, h, x, y = (int(v) for v in crop.split(":"))
    px, py = max(0, -x), max(0, -y)
    vf = (f"pad=iw+{px}:ih+{py}:{px}:{py}:black," if px or py else "") + \
        f"crop={w}:{h}:{x + px}:{y + py}," + "scale=320:200:flags=area,pad=320:232:0:0:black,format=gray"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", str(max(0, t0)),
                    "-to", str(t1), "-i", src, "-vf", vf, "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "12", out], check=True)
    return tag


def churn(tag, t0, t1):
    """what the encoder does to a frame of this capture while nothing happens."""
    v = os.path.join(WORK, f"{tag}.320.mp4")
    prev = None
    ds = []
    for f in RV.frames(v, t0=t0, t1=t1):
        g = f[8:192]
        if prev is not None:
            ds.append(float(np.abs(g - prev).mean()))
        prev = g
    d = np.array(ds)
    return float(np.median(d)), float(np.percentile(d, 95)), int((d > 18.0).sum())


def main():
    recs = json.load(open(os.path.join(HERE, "..", "human_sessions.json")))
    print(f"{'video':16s} {'in house':>9s} {'tile':>5s} {'adv@6':>6s} {'adv@gap':>8s} {'thr':>6s} "
          f"{'old':>5s} {'churn med/p95':>14s} {'>18':>4s}")
    for rec in recs:
        tag = prep(rec)
        if tag is None:
            print(f"{rec['id']:16s} source not on disk")
            continue
        t0, t1 = 1.0, rec["crossing_s"] - max(0.0, rec["start_s"] - 1.0) + 1.0
        r = RV.steps_gap(tag, t0, t1)
        med, p95, big = churn(tag, t0, t1)
        print(f"{rec['id']:16s} {rec['crossing_s'] - rec['start_s']:8.1f}s {r['tile_steps']:5d} "
              f"{r['advances_at_6']:6d} {r['screen_advances']:8d} {r['threshold']:6.2f} "
              f"{str(rec['steps_to_map']):>5s} {med:6.2f}/{p95:5.2f} {big:4d}")


if __name__ == "__main__":
    main()
