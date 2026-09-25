"""Panorama of a walk in a play video and the hero's path through it, for the
three panels of the human route figure in the paper.

    python route.py <clip.mp4> <t0> <t1> <out.png> [start=x,y] [centre|hybrid]

The clip is a colour capture scaled to the native 320x200 frame (ffmpeg
scale=320:200:flags=area). Consecutive frames are registered by phase
correlation, and the background is the per-channel median over the frames near
a camera move, which drops the walking hero. His path is the densest 24x40
block of pixels that differ from the background, kept within 80 px of the last
position; `centre` takes the screen centre instead (the world map keeps the
hero centred), and `hybrid` takes the centre while the view scrolls and the
tracked sprite while it is clamped at a scene border. The figure in the paper
was made from the speedrun BV1UxvTz3Ehe, clip = the source from 6.0 s:
the compound 1.2-10.1 s with start=146,78, the world map 11.5-19.3 s centre,
and the house of the hermit 20.6-22.7 s hybrid.
"""

import subprocess, sys
import numpy as np
from PIL import Image

video, t0, t1, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
start, centre, hybrid = None, False, False
for a in sys.argv[5:]:
    if a.startswith("start="):
        start = tuple(float(v) for v in a[6:].split(","))
    if a == "centre":
        centre = True
    if a == "hybrid":
        hybrid = True
W0, H0 = 320, 200
R0, R1 = 8, 192

def fps_of(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    a, b = o.split("/") if "/" in o else (o, "1"); return float(a) / float(b)

def frames(path, t0, t1):
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(t0), "-i", path, "-t", str(t1 - t0),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        buf = p.stdout.read(W0 * H0 * 3)
        if len(buf) < W0 * H0 * 3: break
        yield np.frombuffer(buf, np.uint8).reshape(H0, W0, 3)
    p.stdout.close(); p.wait()

def shift(a, b):
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)
    fa = np.fft.rfft2((a - a.mean()) * win); fb = np.fft.rfft2((b - b.mean()) * win)
    r = fa * np.conj(fb); r /= np.abs(r) + 1e-6
    c = np.fft.irfft2(r, s=a.shape)
    y, x = np.unravel_index(np.argmax(c), c.shape); peak = float(c[y, x])
    if y > a.shape[0] // 2: y -= a.shape[0]
    if x > a.shape[1] // 2: x -= a.shape[1]
    return x, y, peak

fps = fps_of(video)
col = list(frames(video, t0, t1))
gray = [f.astype(np.float32).mean(axis=2) for f in col]
print("frames", len(col), "fps", round(fps, 2))
offs, moved = [(0, 0)], [False]
prev = gray[0]
for g in gray[1:]:
    dx, dy, peak = shift(prev[R0:R1], g[R0:R1])
    if peak < 0.15 or abs(dx) > 60 or abs(dy) > 60:
        dx, dy = 0, 0
    offs.append((offs[-1][0] + dx, offs[-1][1] + dy)); moved.append((dx, dy) != (0, 0))
    prev = g
xs = [o[0] for o in offs]; ys = [o[1] for o in offs]
minx, miny = min(xs), min(ys)
W, Hh = max(xs) - minx + W0, max(ys) - miny + H0
win = int(fps * 0.6)
near = [any(moved[max(0, i - win):i + win + 1]) for i in range(len(col))]
use = [i for i in range(len(col)) if near[i]] or list(range(len(col)))
print("canvas", W, Hh, "background frames", len(use))
bg = np.zeros((Hh, W, 3), np.float32)
for ch in range(3):
    stack = np.full((len(use), Hh, W), np.nan, np.float16)
    for k, i in enumerate(use):
        ox, oy = offs[i][0] - minx, offs[i][1] - miny
        stack[k, oy:oy + H0, ox:ox + W0] = col[i][:, :, ch]
    with np.errstate(all="ignore"):
        bg[:, :, ch] = np.nanmedian(stack.astype(np.float32), axis=0)
    del stack
bgg = bg.mean(axis=2)
path = [] if start is None else [(start[0] - minx, start[1] - miny, t0)]
last = path[-1] if path else None
for i, g in enumerate(gray):
    if centre or (hybrid and moved[i]):
        last = (offs[i][0] - minx + W0 / 2, offs[i][1] - miny + H0 / 2 + 8, t0 + i / fps); path.append(last); continue
    ox, oy = offs[i][0] - minx, offs[i][1] - miny
    d = np.abs(g - bgg[oy:oy + H0, ox:ox + W0]) > 40
    d[:R0] = False; d[R1:] = False
    if d.mean() > 0.2 or d.sum() < 40:
        continue
    c = np.pad(d.astype(np.float32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    bh, bw = 40, 24
    s = c[bh:, bw:] - c[:-bh, bw:] - c[bh:, :-bw] + c[:-bh, :-bw]
    if last is not None:
        yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]]
        far = (np.abs(xx + ox + bw / 2 - last[0]) > 80) | (np.abs(yy + oy + bh * 0.75 - last[1]) > 80)
        s = np.where(far, 0, s)
    yy, xx = np.unravel_index(np.argmax(s), s.shape)
    if s[yy, xx] >= 60:
        last = (ox + xx + bw / 2, oy + yy + bh * 0.75, t0 + i / fps); path.append(last)
# smooth: drop a point that jumps 50 px from both neighbours, then a running mean of three
if len(path) > 4 and not centre:
    keep = [path[0]] + [p for a, p, b in zip(path, path[1:], path[2:])
                        if not (abs(p[0] - a[0]) + abs(p[1] - a[1]) > 50 and abs(p[0] - b[0]) + abs(p[1] - b[1]) > 50)] + [path[-1]]
    path = [keep[0]] + [((a[0] + p[0] + b[0]) / 3, (a[1] + p[1] + b[1]) / 3, p[2]) for a, p, b in zip(keep, keep[1:], keep[2:])] + [keep[-1]]
print("path points", len(path))
# the panel is the background alone; ../human_route.py draws the path from the
# JSON beside it, one row per point with the second of the clip
Image.fromarray(np.nan_to_num(bg, nan=0).clip(0, 255).astype(np.uint8)).save(out)
import json
json.dump({"clip": video, "t0": t0, "t1": t1, "columns": ["x", "y", "second"],
           "rows": [[round(float(x), 1), round(float(y), 1), round(float(t), 2)] for x, y, t in path]},
          open(out[:-4] + "-path.json", "w"))
print("wrote", out, "and", out[:-4] + "-path.json", (W, Hh))
