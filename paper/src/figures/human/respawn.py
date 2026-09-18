"""Re-anchor every capture to the same starting state: the hero on his tile, back to us.

    python3 respawn.py [id ...]

A teaser is not play, and neither is the opening room while the game still has the hero
lying on the floor or standing face-on to the camera. A benchmark session begins at frame
zero with him standing on his spawn tile in the home, seen from behind, facing the red
five-pointed star on the chair - templates/room.png is that frame - so a human capture is
counted from the first frame in the same state. The crossing is the first black frame a
second after it, and every milestone minute of a video is measured from the same frame, so
this is where the clock of the human rows of the ladder is set.

Facing is read off the hero's head, matched twice: against the back of the head taken from
frame zero, and against a face taken from a capture in which he stands face-on to the
camera. A head scored against the wrong filter returns near zero, so the sign of the
difference says which way he looks and the size of it says how clean the capture is - a
sharp rip of the DOS binary gives 0.96 against -0.05, a blurred stream of the same moment
0.46 against -0.06. One threshold across captures cannot work. So the box is aligned to
each capture first, over a grid of four pixels, on the upper quartile of the back score so
that the alignment follows the sprite and not the noise, and then one low margin on the
difference, held half a second, names the frame. The frames around every boundary are
written out as sheets, and every start printed here was looked at on those sheets.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

import read_video as RV
import spawnscan as SS

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
HOLD, GAP, BLACK, MARGIN, ALIGN = 0.5, 2.0, 12.0, 0.15, 4
HX0, HY0, HX1, HY1 = SS.HEAD_BOX
SX0, SY0, SX1, SY1 = SS.SPAWN_BOX
# the two heads the hero can show at his tile: the back of his head is frame zero of a
# replay, his face is a frame of a capture in which he stands face-on to the camera. Both
# are kept as templates, so the anchor does not depend on a scratch video still being there
BACK = np.asarray(Image.open(os.path.join(HERE, "templates", "head-back.png")).convert("L"), np.float32)
FACEPATH = os.path.join(HERE, "templates", "head-face.png")
FACE = np.asarray(Image.open(FACEPATH).convert("L"), np.float32) if os.path.exists(FACEPATH) else None


def face_ref():
    """the face template, or nothing: a capture is gated on the room before it is anchored,
    and only the anchor needs to know what his face looks like."""
    if FACE is None:
        raise SystemExit("templates/head-face.png is missing: extract it from a frame in which "
                         "the hero stands face-on (see README), then rerun")
    return FACE


def score(h, tpl):
    return float(RV.ncc_max(h, tpl)) if h.shape == tpl.shape else -1.0


def source(rec):
    if rec.get("video"):
        v = rec["video"]
        return v if os.path.isabs(v) else (v if os.path.exists(v) else os.path.join(WORK, v))
    for cand in (f"{rec['id']}.mp4", f"{rec['id']}.320.mp4"):
        p = os.path.join(WORK, cand)
        if os.path.exists(p):
            return p
    return None


def decode(vid, crop, t0, t1):
    """one pass: the room score, the luminance, the head with a margin for alignment, and
    the spawn tile for the sheet. Nothing else is kept, so a five-hour stream fits in RAM."""
    m = ALIGN
    out = []
    for i, f in enumerate(SS.frames_of(vid, crop, t0, t1)):
        out.append(dict(t=t0 + i / RV.fps_of(vid), room=SS.room(f), lum=float(f[:200].mean()),
                        hd=f[HY0 - m:HY1 + m, HX0 - m:HX1 + m].astype(np.uint8),
                        sp=f[SY0:SY1, SX0:SX1].astype(np.uint8)))
    return out


def align(fr, fps, gate):
    """the offset of the head box that follows the sprite, on its best score. The upper
    quartile of the whole window would follow the floor instead, because most of the
    window is the opening in which he lies or fades; the peak of the frames in which the
    home is on screen can only come from the sprite itself."""
    samp = [r for r in fr[::max(1, int(fps * 0.3))] if r["room"] >= gate]
    m = ALIGN
    grid = {}
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            vals = [score(r["hd"][m + dy:m + HY1 - HY0 + dy, m + dx:m + HX1 - HX0 + dx], BACK)
                    for r in samp]
            grid[(dx, dy)] = float(np.percentile(vals, 90)) if vals else -1.0
    dx, dy = max(grid, key=grid.get)
    return dx, dy, grid[(dx, dy)]


def run(rec, t0, t1):
    vid, crop = source(rec), rec.get("crop") or "-"
    fps = RV.fps_of(vid)
    fr = decode(vid, crop, t0, t1)
    if len(fr) < 20:
        print(f"{rec['id']}: nothing decoded in {t0:.0f}-{t1:.0f}s")
        return None
    gate = max(0.55, 0.72 * max(r["room"] for r in fr))       # the home on screen
    dx, dy, q = align(fr, fps, gate)
    m = ALIGN
    for r in fr:
        h = r["hd"][m + dy:m + HY1 - HY0 + dy, m + dx:m + HX1 - HX0 + dx]
        r["back"], r["face"] = score(h, BACK), score(h, face_ref())

    start, run_, ok_prev = None, None, None
    for r in fr:
        ok = r["back"] - r["face"] >= MARGIN and r["room"] >= gate
        if ok:
            if run_ is None or r["t"] - ok_prev > GAP / fps:
                run_ = r["t"]
            if start is None and r["t"] - run_ >= HOLD:
                start = round(run_, 3)
            ok_prev = r["t"]
        else:
            run_ = None
    cross = next((round(r["t"], 3) for r in fr if start and r["t"] >= start + 1.0 and r["lum"] < BLACK), None)

    name = rec["id"]
    rows = [(r["t"], f"{r['back']:.2f}/{r['face']:.2f}", r["sp"]) for r in fr
            if start and abs(r["t"] - start) <= 3.0 and int(round(r["t"] * fps)) % max(1, int(fps * 0.34)) == 0]
    if rows:
        cols, tile = 5, 2.6
        w, hh = int((SX1 - SX0) * tile), int((SY1 - SY0) * tile)
        out = Image.new("L", (w * cols, (hh + 13) * ((len(rows) + cols - 1) // cols)), 0)
        d = ImageDraw.Draw(out)
        for i, (t, txt, sp) in enumerate(rows):
            x, y = (i % cols) * w, (i // cols) * (hh + 13)
            out.paste(Image.fromarray(sp).resize((w, hh), Image.NEAREST), (x, y))
            d.rectangle((x, y, x + w, y + 12), fill=0)
            d.text((x + 2, y + 2), f"{t:.2f}s back/face {txt}", fill=255)
        out.save(os.path.join(WORK, f"{name}-in.png"))
    marg = [r["back"] - r["face"] for r in fr if r["room"] >= gate]
    print(f"{name:16s} {rec['class']:11s} align ({dx:+d},{dy:+d}) p75back {q:.2f} "
          f"margin {min(marg):.2f}..{max(marg):.2f} n={len(marg)}")
    print(f"{'':16s} START {start if start is None else format(start,'7.2f')}s (was {rec['start_s']:7.2f})"
          f"  CROSS {cross if cross is None else format(cross,'7.2f')}s (was {rec['crossing_s']:7.2f})"
          f"  sheet {name}-in.png")
    return start, cross


if __name__ == "__main__":
    recs = json.load(open(os.path.join(HERE, "..", "human_sessions.json")))
    want = sys.argv[1:]
    for rec in recs:
        if want and rec["id"] not in want:
            continue
        if not source(rec):
            print(f"{rec['id']}: source not downloaded")
            continue
        run(rec, 0.0, float(rec["crossing_s"]) + 2.0)
