"""Fit the game frame of a capture, then say where play starts in it.

    python3 cropfit.py <video> [t0] [t1]

The capture is swept for the opening room of a benchmark replay at every scale it could
hold (`read_video.findcrop` does the same at one second); the scale that wins fixes a
nominal frame, whose width, height and offset are then searched by whole pixels against
the three frames where the room scores highest, since a capture is stretched and clipped
by its player and the frame the scale search names is not the frame ffmpeg will cut.
The fitted crop is printed with the first frame of the room in the fitted frame, which
is where play starts, and the black frame after it, which is the crossing.
"""
import subprocess
import sys

import numpy as np
from PIL import Image

import read_video as RV
import replay_scan as R

TPL = RV.ROOM[70:190, 24:296]
BX0, BY0, BX1, BY1 = RV.ROOM_BOX


def score(f):
    return float(RV.ncc_max(f[BY0 - RV.SEARCH:BY1 + RV.SEARCH, BX0 - RV.SEARCH:BX1 + RV.SEARCH], TPL))


def fit(src, w0, h0, span=6, step=2):
    Ws, Hs = src.shape[1], src.shape[0]
    best = (-1.0, None)
    for h in range(max(40, h0 - span), min(Hs, h0 + span) + 1, step):
        for w in range(max(40, w0 - span), min(Ws, w0 + span) + 1, step):
            for y in range(max(0, (Hs - h) // 2 - 14), min(Hs - h, (Hs - h) // 2 + 14) + 1, step):
                for x in range(max(0, (Ws - w) // 2 - 14), min(Ws - w, (Ws - w) // 2 + 14) + 1, step):
                    f = np.asarray(Image.fromarray(src[y:y + h, x:x + w].astype(np.uint8)).resize(
                        (320, 200), Image.BILINEAR), dtype=np.float32)
                    v = score(np.pad(f, ((0, 32), (0, 0)), constant_values=0))
                    if v > best[0]:
                        best = (v, (w, h, x, y))
    return best


def main(video, t0=0.0, t1=420.0):
    Ws, Hs = RV.native_size(video)
    tpl = RV.ROOM[BY0:BY1, BX0:BX1]
    cache = {}

    def scaled(sx, sy):
        if (sx, sy) not in cache:
            rt = np.asarray(Image.fromarray(tpl.astype(np.uint8)).resize(
                (int(round((BX1 - BX0) * sx)), int(round((BY1 - BY0) * sy))), Image.BILINEAR), dtype=np.float32)
            cache[(sx, sy)] = rt if rt.shape[0] < Hs and rt.shape[1] < Ws else None
        return cache[(sx, sy)]

    grid = [(sx, sy) for sx in np.arange(1.0, 2.61, 0.05) for sy in np.arange(0.9, 2.61, 0.05)
            if 0.5 * Ws <= 320 * sx <= 1.02 * Ws and 0.5 * Hs <= 200 * sy <= 1.02 * Hs
            and scaled(sx, sy) is not None]
    hits = []
    for i, src in enumerate(RV.native_frames(video, t1=t1, fps=0.5)):
        t = t0 + i * 2
        row = (-1.0, None)
        for sx, sy in grid:
            m = RV.ncc_map(src, scaled(sx, sy))
            y, x = np.unravel_index(np.argmax(m), m.shape)
            v = float(m[y, x])
            if 0.5 < v <= 0.999 and v > row[0]:
                row = (v, (sx, sy, int(x), int(y)))
        if row[1]:
            hits.append((row[0], t, row[1]))
    if not hits:
        print(f"{video}: no opening room in the first {t1:.0f}s")
        return 1
    hits.sort(key=lambda h: -h[0])
    print("room frames:", ", ".join(f"{t:.1f}s ncc {v:.3f}" for v, t, _ in hits[:4]))
    top = hits[:3]
    agg = {}
    for v, t, (sx, sy, x, y) in top:
        src = RV.frame_at(video, t)
        # the nominal frame the scale search names, before ffmpeg clamps it
        nw, nh = int(round(320 * sx)), int(round(200 * sy))
        nx, ny = int(round(x - BX0 * sx)), int(round(y - BY0 * sy))
        nw = min(nw, Ws); nh = min(nh, Hs)
        nx = max(0, min(nx, Ws - nw)); ny = max(0, min(ny, Hs - nh))
        s, box = fit(src, nw, nh)
        agg[box] = agg.get(box, 0.0) + s
    box = max(agg, key=agg.get)
    w, h, x, y = box
    scores = []
    for _, t, _ in top:
        src = RV.frame_at(video, t)
        f = np.asarray(Image.fromarray(src[y:y + h, x:x + w].astype(np.uint8)).resize(
            (320, 200), Image.BILINEAR), dtype=np.float32)
        scores.append(score(np.pad(f, ((0, 32), (0, 0)), constant_values=0)))
    print(f"crop {w}:{h}:{x}:{y} ncc {' '.join(f'{s:.3f}' for s in scores)} in {Ws}x{Hs}")
    return 0


if __name__ == "__main__":
    main(sys.argv[1], *[float(a) for a in sys.argv[2:]])
