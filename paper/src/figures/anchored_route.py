"""A model's walk through the opening compound, placed frame by frame on a
fixed panorama of the compound, with its path drawn on it.

    python anchored_route.py <session id> [<out.png>]

model_route.py chains the shift between consecutive frames, which drifts on
the open grass of the yard when a replay is recorded at a high speed and the
view jumps several tiles between frames. Here every frame of the replay, up to
its first black frame, is placed directly on human/templates/compound-bg.png,
the compound stitched from a human speedrun with the hero removed, at the
offset of highest normalised cross-correlation; frames with a dialogue box or
a menu correlate poorly and are skipped. The hero is followed on screen from
the spawn tile: while the view stays put, he is the densest 24x40 block of
change between consecutive frames near his last screen position, and while
the view scrolls the game keeps him where he stands on screen. His place on
the compound is the offset of the frame plus his screen position. The path is drawn on the panorama
in red from the circle to the square, and a .txt stamp names the session.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "human"))
import field  # noqa: E402
import read_video as RV  # noqa: E402

W0, H0 = 320, 200
PANO = os.path.join(HERE, "human", "templates", "compound-bg.png")
SPAWN = (146, 78)          # the spawn tile in the first frame, as in human/route.py
MIN_NCC = 0.55


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


def main():
    sid = sys.argv[1]
    row = next(r for r in field.load_runs(dedup=False, keep_excluded=True) if r["id"] == sid)
    ev = json.load(open(os.path.join(HERE, "replay_events.json"), encoding="utf-8"))[sid]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, f"route-model-{row['agent']}.png")
    video = os.path.join(HERE, "videos", sid + ".mp4")
    if not os.path.exists(video):
        import urllib.request
        os.makedirs(os.path.dirname(video), exist_ok=True)
        urllib.request.urlretrieve(row["video_url"], video)
    pano = np.asarray(Image.open(PANO).convert("RGB"), np.float32)
    pg = pano.mean(axis=2)
    path, placed = [], 0
    screen, prev = SPAWN, None
    for i, f in enumerate(frames(video, ev["first_black_second"])):
        g = f.astype(np.float32).mean(axis=2)
        m = RV.ncc_map(pg, g)
        y, x = np.unravel_index(np.argmax(m), m.shape)
        if m[y, x] < MIN_NCC:
            continue
        placed += 1
        if prev is not None and (x, y) == prev[1]:
            d = np.abs(g - prev[0]) > 30
            d[:8] = False
            d[192:] = False
            if d.sum() >= 40:
                c = np.pad(d.astype(np.float32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                bh, bw = 40, 24
                s_ = c[bh:, bw:] - c[:-bh, bw:] - c[bh:, :-bw] + c[:-bh, :-bw]
                yy, xx = np.mgrid[0:s_.shape[0], 0:s_.shape[1]]
                far = (np.abs(xx + bw / 2 - screen[0]) > 60) | (np.abs(yy + bh * 0.75 - screen[1]) > 60)
                s_ = np.where(far, 0, s_)
                by, bx = np.unravel_index(np.argmax(s_), s_.shape)
                if s_[by, bx] >= 60:
                    screen = (bx + bw / 2, by + bh * 0.75)
        prev = (g, (x, y))
        path.append((x + screen[0], y + screen[1]))
    print(sid, row["agent"], "frames placed", placed, "path points", len(path))
    # a running mean of three, as in human/route.py
    if len(path) > 4:
        path = [path[0]] + [((a[0] + p[0] + b[0]) / 3, (a[1] + p[1] + b[1]) / 3)
                            for a, p, b in zip(path, path[1:], path[2:])] + [path[-1]]
    im = Image.fromarray(pano.clip(0, 255).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    dr.line(path, fill=(230, 40, 40), width=3)
    x0, y0 = path[0]
    dr.ellipse((x0 - 6, y0 - 6, x0 + 6, y0 + 6), fill=(230, 40, 40), outline=(255, 255, 255), width=2)
    x1, y1 = path[-1]
    dr.rectangle((x1 - 6, y1 - 6, x1 + 6, y1 + 6), fill=(230, 40, 40), outline=(255, 255, 255), width=2)
    im.save(out)
    with open(out[:-4] + ".txt", "w") as fh:
        fh.write(sid + "\n")
    print("wrote", out, im.size)


if __name__ == "__main__":
    main()
