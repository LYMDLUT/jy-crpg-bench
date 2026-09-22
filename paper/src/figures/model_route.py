"""Panorama of a model's walk through the opening compound, with its path drawn
on it: the model panels of the route figure in the paper.

    python model_route.py <session id> [<out.png>]

The replay of the session is fetched from its video_url on the catalogue (or
read from videos/<id>.mp4), cropped to the 320x200 game frame above the status
bar, and cut at the first black frame of the replay, which the replay scan
records as the crossing to the world map. Frames with a dialogue box or a menu
are dropped before registration, since their white text and black panel break
the phase correlation and the sprite tracker. Registration, background and
tracking then follow human/route.py: consecutive frames are aligned by phase
correlation, the background is the per-pixel median near a camera move, which
removes the hero, and his path is the densest block of pixels that differ from
the background within 80 px of the last position, starting on the spawn tile.
"""

import json, os, subprocess, sys, urllib.request
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import field

W0, H0 = 320, 200          # game frame; the replay adds a 32 px status bar below
R0, R1 = 8, 192
SPAWN = (146, 78)          # the spawn tile in frame coordinates, as in human/route.py
DIALOGUE_WHITE, DIALOGUE_BLACK = 300, 800   # pixels: a dialogue box has both a white text run and a black panel


def fps_of(path):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    a, b = o.split("/") if "/" in o else (o, "1")
    return float(a) / float(b)


def frames(path, t1):
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-t", str(t1),
           "-vf", f"crop={W0}:{H0}:0:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        buf = p.stdout.read(W0 * H0 * 3)
        if len(buf) < W0 * H0 * 3:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H0, W0, 3)
    p.stdout.close()
    p.wait()


def is_dialogue(f):
    return (f.min(axis=2) > 225).sum() > DIALOGUE_WHITE and (f.max(axis=2) < 20).sum() > DIALOGUE_BLACK


def shift(a, b):
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)
    fa = np.fft.rfft2((a - a.mean()) * win)
    fb = np.fft.rfft2((b - b.mean()) * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-6
    c = np.fft.irfft2(r, s=a.shape)
    y, x = np.unravel_index(np.argmax(c), c.shape)
    peak = float(c[y, x])
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return x, y, peak


def overlap_error(a, b, dx, dy):
    """Mean absolute difference between a and b placed dx, dy from it."""
    h, w = a.shape
    ax0, ax1 = max(0, dx), min(w, w + dx)
    ay0, ay1 = max(0, dy), min(h, h + dy)
    if ax1 - ax0 < w // 2 or ay1 - ay0 < h // 2:
        return np.inf
    return float(np.abs(a[ay0:ay1, ax0:ax1] - b[ay0 - dy:ay1 - dy, ax0 - dx:ax1 - dx]).mean())


def verified_shift(a, b, limit=60, peaks=6):
    """The shift from a to b: the phase correlation proposes its highest peaks,
    the tile-periodic fence and grass of the compound make a shift of one tile
    look like none, so the candidates and no shift are checked by the overlap
    error and the lowest error wins."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)
    fa = np.fft.rfft2((a - a.mean()) * win)
    fb = np.fft.rfft2((b - b.mean()) * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-6
    c = np.fft.irfft2(r, s=a.shape)
    cands = {(0, 0)}
    flat = np.argsort(c.ravel())[::-1][:peaks]
    for idx in flat:
        y, x = np.unravel_index(idx, c.shape)
        if y > a.shape[0] // 2:
            y -= a.shape[0]
        if x > a.shape[1] // 2:
            x -= a.shape[1]
        if abs(x) <= limit and abs(y) <= limit:
            cands.add((int(x), int(y)))
    best = min(cands, key=lambda s: overlap_error(a, b, *s))
    return best[0], best[1], overlap_error(a, b, *best)


def panorama(video, t1, out, fps):
    # The replay holds a frame while the model thinks, so most frames repeat the
    # last one with the hero standing still; a run of such frames is collapsed
    # to one, or the standing hero would enter the background median.
    col, total = [], 0
    for f in frames(video, t1):
        total += 1
        if is_dialogue(f):
            continue
        if col and (np.abs(f.astype(np.int16) - col[-1].astype(np.int16)).max(axis=2) > 30)[R0:R1].sum() < 30:
            continue
        col.append(f)
    gray = [f.astype(np.float32).mean(axis=2) for f in col]
    print("frames kept", len(col), "of", total, "fps", round(fps, 2))
    offs, moved = [(0, 0)], [False]
    prev = gray[0]
    for g in gray[1:]:
        dx, dy, err = verified_shift(prev[R0:R1], g[R0:R1])
        if err > 40:
            dx, dy = 0, 0
        offs.append((offs[-1][0] + dx, offs[-1][1] + dy))
        moved.append((dx, dy) != (0, 0))
        prev = g
    xs = [o[0] for o in offs]
    ys = [o[1] for o in offs]
    minx, miny = min(xs), min(ys)
    W, Hh = max(xs) - minx + W0, max(ys) - miny + H0
    use = list(range(len(col)))
    print("canvas", W, Hh, "background frames", len(use))

    def median_background(offs, minx, miny, W, Hh):
        bg = np.zeros((Hh, W, 3), np.float32)
        for ch in range(3):
            stack = np.full((len(use), Hh, W), np.nan, np.float16)
            for k, i in enumerate(use):
                ox, oy = offs[i][0] - minx, offs[i][1] - miny
                stack[k, oy:oy + H0, ox:ox + W0] = col[i][:, :, ch]
            with np.errstate(all="ignore"):
                bg[:, :, ch] = np.nanmedian(stack.astype(np.float32), axis=0)
            del stack
        return bg

    bg = median_background(offs, minx, miny, W, Hh)
    # A long walk accumulates drift in the chain of frame-to-frame shifts, so a
    # second pass registers each frame against the median panorama of the first
    # and the background is recomputed from the corrected offsets.
    bgg = bg.mean(axis=2)
    fixed = []
    for i, g in enumerate(gray):
        ox, oy = offs[i][0] - minx, offs[i][1] - miny
        ref = bgg[oy + R0:oy + R1, ox:ox + W0]
        filled = np.where(np.isnan(ref), g[R0:R1], ref)
        dx, dy, err = verified_shift(filled, g[R0:R1], limit=40)
        if err > 40:
            dx, dy = 0, 0
        fixed.append((offs[i][0] + dx, offs[i][1] + dy))
    moved = [False] + [a != b for a, b in zip(fixed, fixed[1:])]
    offs = fixed
    xs = [o[0] for o in offs]
    ys = [o[1] for o in offs]
    minx, miny = min(xs), min(ys)
    W, Hh = max(xs) - minx + W0, max(ys) - miny + H0
    print("canvas after refinement", W, Hh)
    bg = median_background(offs, minx, miny, W, Hh)
    bgg = bg.mean(axis=2)
    # The scene scrolls to keep the hero on his tile while the view can move, so
    # while the camera moves his position is the spawn tile of the frame, as in
    # the `hybrid` mode of human/route.py; only when the view is clamped at a
    # border does the sprite move across the screen and is tracked.
    path = [(SPAWN[0] - minx, SPAWN[1] - miny)]
    last = path[-1]
    for i, g in enumerate(gray):
        ox, oy = offs[i][0] - minx, offs[i][1] - miny
        if moved[i]:
            last = (ox + SPAWN[0], oy + SPAWN[1])
            path.append(last)
            continue
        d = np.abs(g - bgg[oy:oy + H0, ox:ox + W0]) > 40
        d[:R0] = False
        d[R1:] = False
        if d.mean() > 0.2 or d.sum() < 40:
            continue
        c = np.pad(d.astype(np.float32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        bh, bw = 40, 24
        s = c[bh:, bw:] - c[:-bh, bw:] - c[bh:, :-bw] + c[:-bh, :-bw]
        yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]]
        far = (np.abs(xx + ox + bw / 2 - last[0]) > 80) | (np.abs(yy + oy + bh * 0.75 - last[1]) > 80)
        s = np.where(far, 0, s)
        yy, xx = np.unravel_index(np.argmax(s), s.shape)
        if s[yy, xx] >= 60:
            last = (ox + xx + bw / 2, oy + yy + bh * 0.75)
            path.append(last)
    if len(path) > 4:
        keep = [path[0]] + [p for a, p, b in zip(path, path[1:], path[2:])
                            if not (abs(p[0] - a[0]) + abs(p[1] - a[1]) > 50 and abs(p[0] - b[0]) + abs(p[1] - b[1]) > 50)] + [path[-1]]
        path = [keep[0]] + [((a[0] + p[0] + b[0]) / 3, (a[1] + p[1] + b[1]) / 3) for a, p, b in zip(keep, keep[1:], keep[2:])] + [keep[-1]]
    print("path points", len(path))
    np.save(out[:-4] + "-path.npy", np.array(path, np.float32))
    im = Image.fromarray(np.nan_to_num(bg, nan=0).clip(0, 255).astype(np.uint8))
    im.save(out[:-4] + "-bg.png")
    dr = ImageDraw.Draw(im)
    pts = [(x, y) for x, y in path]
    if len(pts) > 1:
        dr.line(pts, fill=(230, 40, 40), width=3)
        x, y = pts[0]
        dr.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(230, 40, 40), outline=(255, 255, 255), width=2)
        x, y = pts[-1]
        dr.rectangle((x - 6, y - 6, x + 6, y + 6), fill=(230, 40, 40), outline=(255, 255, 255), width=2)
    im.save(out)
    print("wrote", out, im.size)


def main():
    sid = sys.argv[1]
    events = json.load(open(os.path.join(HERE, "replay_events.json"), encoding="utf-8"))
    if sid not in events or events[sid].get("first_black_second") is None:
        sys.exit(f"{sid}: no crossing in replay_events.json")
    row = next((r for r in field.load_runs(dedup=False, keep_excluded=True) if r["id"] == sid), None)
    if row is None:
        sys.exit(f"{sid}: not in the catalogue")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, f"route-model-{row['agent']}.png")
    vdir = os.path.join(HERE, "videos")
    os.makedirs(vdir, exist_ok=True)
    video = os.path.join(vdir, sid + ".mp4")
    if not os.path.exists(video):
        urllib.request.urlretrieve(row["video_url"], video)
    t1 = float(events[sid]["first_black_second"])
    print(row["agent"], sid, "crossing at video second", t1, "after", events[sid]["crossing_actions"], "actions")
    panorama(video, t1, out, fps_of(video))
    with open(out[:-4] + ".txt", "w") as f:
        f.write(sid + "\n")


if __name__ == "__main__":
    main()
