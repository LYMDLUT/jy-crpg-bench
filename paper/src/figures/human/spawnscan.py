"""Where a capture's clock starts: the hero standing on his tile, facing the soft-star.

    python3 spawnscan.py facing <video> <crop|-> [t0] [t1]
    python3 spawnscan.py pose    <video> <crop|-> [t0] [t1]

A teaser is not play, and neither is the home while the game's opening still has the hero
lying on the floor or standing face-on to the camera. A benchmark session begins at frame
zero with him standing on his spawn tile in the home, seen from behind, looking at the red
five-pointed star on the chair - the template in templates/room.png is that frame - so a
human capture is counted from the first frame in the same state.

`pose` scores the box of the hero and the star against the template. `facing` adds the
other side of the question: the same head matched against a captured head-on frame, since
a face and the back of a head are only about ten gray levels apart at 320x200 and do not
threshold apart cleanly. The clock starts where back beats front by `margin` and holds.
Both write sheets of the frames around the boundary, one tile per frame, for the eye.
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

import read_video as RV

TEMPLATE = RV.ROOM                              # 320x232, frame zero of a benchmark replay
SPAWN_BOX = (135, 42, 200, 112)               # the hero's sprite and shadow, and the star
HEAD_BOX = (137, 58, 155, 78)                 # the hero's head on his spawn tile
TPL = TEMPLATE[SPAWN_BOX[1]:SPAWN_BOX[3], SPAWN_BOX[0]:SPAWN_BOX[2]]
FRONT_HEAD = None                             # a captured face-on head, from a video at run


def score(f):
    """the hero-and-star box against the template: high only when he is at the tile."""
    x0, y0, x1, y1 = SPAWN_BOX
    return float(RV.ncc_max(f[y0 - RV.SEARCH:y1 + RV.SEARCH, x0 - RV.SEARCH:x1 + RV.SEARCH], TPL))


def room(f):
    """the home itself, without the hero: is the room on screen, or still fading in."""
    x0, y0, x1, y1 = RV.ROOM_BOX
    return float(RV.ncc_max(f[y0 - RV.SEARCH:y1 + RV.SEARCH, x0 - RV.SEARCH:x1 + RV.SEARCH],
                             RV.ROOM[y0 - RV.SEARCH:y1 + RV.SEARCH, x0 - RV.SEARCH:x1 + RV.SEARCH]))


def frames_of(video, crop, t0, t1):
    """the capture cut to the native frame, decoded between two seconds."""
    if video.endswith(".320.mp4"):
        yield from RV.frames(video, t0=float(t0), t1=float(t1))
        return
    w, h, x, y = (int(v) for v in crop.split(":")) if crop not in (None, "", "-") else \
        tuple(RV.native_size(video)) + (0, 0)
    px, py = max(0, -x), max(0, -y)
    vf = (f"pad=iw+{px}:ih+{py}:{px}:{py}:black," if px or py else "") + \
        f"crop={w}:{h}:{x + px}:{y + py}," + "scale=320:200:flags=area,pad=320:232:0:0:black,format=gray"
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(t0), "-i", video,
           "-t", str(t1 - t0), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        buf = proc.stdout.read(320 * 232)
        if len(buf) < 320 * 232:
            break
        yield np.frombuffer(buf, np.uint8).reshape(232, 320).astype(np.float32)
    proc.stdout.close()
    proc.wait()


def sheet(path, rows, box, cols=4, tile=3.0, label=""):
    """one tile per frame: the box blown up, the second and its scores on top."""
    x0, y0, x1, y1 = box
    tw, th = int((x1 - x0) * tile), int((y1 - y0) * tile)
    out = Image.new("L", (tw * cols, (th + 14) * ((len(rows) + cols - 1) // cols)), 0)
    d = ImageDraw.Draw(out)
    for i, row in enumerate(rows):
        t, txt, f = row
        im = Image.fromarray(f[:200].astype(np.uint8)).crop((x0, y0, x1, y1)).resize((tw, th), Image.NEAREST)
        x, y = (i % cols) * tw, (i // cols) * (th + 14)
        out.paste(im, (x, y))
        d.rectangle((x, y, x + tw, y + 13), fill=0)
        d.text((x + 3, y + 2), f"{t:.2f}s {txt}", fill=255)
    out.save(path)
    print(f"{label}sheet {path} ({len(rows)} frames)")


def _run(video, crop, t0, t1, mode, thr, margin, hold, front_at, step):
    """mode `pose` gates on the spawn-pose score; `facing` adds the head filter.

    The room has to be on screen for a frame to count: during the fade in from black both
    filters are meaningless, and while the hero is lying on the floor the head box holds
    only floor."""
    fps = RV.fps_of(video)
    global FRONT_HEAD
    if mode == "facing" and FRONT_HEAD is None:
        v, t = front_at if isinstance(front_at, tuple) else (video, front_at or 17.0)
        FRONT_HEAD = RV.frame_at(v, t)[HEAD_BOX[1]:HEAD_BOX[3], HEAD_BOX[0]:HEAD_BOX[2]]
        print(f"{os.path.basename(video)}: face-on reference taken from {v} at {t}s")
    hx0, hy0, hx1, hy1 = HEAD_BOX
    curve, rows, start, held = [], [], None, 0.0
    prev = None
    for i, f in enumerate(frames_of(video, crop, t0, t1)):
        t = t0 + i / fps
        b = score(f)
        g = RV.ncc_max(f[hy0:hy1, hx0:hx1], FRONT_HEAD) - b if mode == "facing" else 0.0
        ok = (b - g >= margin) if mode == "facing" else (b >= thr)
        if room(f) < 0.60:                               # the home is not on screen yet
            ok = False
        curve.append((t, b, g))
        if ok:
            held += (t - prev if prev is not None else 0.0) + 1 / fps
            if start is None and held >= hold:
                start = round(t - held + 1 / fps, 3)
        else:
            held = 0.0
        prev = t
        if step and i % max(1, int(round(fps * step))) == 0:
            rows.append((t, f"b{b:.2f}{' f' + format(g, '.2f') if mode == 'facing' else ''}", f))
    name = os.path.basename(video).split(".")[0]
    bs = [c[1] for c in curve]
    print(f"{name}: {len(curve)} frames {t0:.0f}-{t1:.0f}s, {mode} start "
          f"{start if start is None else str(start) + 's'} | pose {min(bs):.2f}-{max(bs):.2f}"
          + (f" | front-pose {min(c[2] for c in curve):.2f}-{max(c[2] for c in curve):.2f}"
             if mode == "facing" else ""))
    near = [r for r in rows if start is not None and abs(r[0] - start) <= 2.5] or rows[:12]
    sheet(f"work/{name}-{'face' if mode == 'facing' else 'pose'}.png", near,
          HEAD_BOX if mode == "facing" else SPAWN_BOX, label=f"{name}: ")
    return start


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args[0] if args[0] in ("facing", "pose") else "pose"
    a = args if mode != args[0] else args[1:]
    video = a[0]
    crop = a[1] if len(a) > 1 else "-"
    t0 = float(a[2]) if len(a) > 2 else 0.0
    t1 = float(a[3]) if len(a) > 3 else 40.0
    front = (video, float(a[4])) if len(a) > 4 else ("work/david.320.mp4", 17.0)
    _run(video, crop, t0, t1, mode, 0.85, 0.04, 0.5, front, 0.25)
