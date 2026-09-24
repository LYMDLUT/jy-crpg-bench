"""A model's walk through the opening compound, placed frame by frame on a
fixed panorama of the compound, with its path drawn on it.

    python anchored_route.py <session id> [<out.png>]

model_route.py chains the shift between consecutive frames, which drifts on
the open grass of the yard when a replay is recorded at a high speed and the
view jumps several tiles between frames. Here every frame of the replay, up to
its first black frame, is placed directly on a fixed panorama of the compound
at the offset of highest normalised cross-correlation, so every session lands
on the same picture and the panels of the figure can be compared.

The panorama is compound.png in this directory, built by compound_panorama.py
from human/templates/compound-bg.png, the compound stitched from a human
speedrun with the hero removed, and from the wider stitch of a model session
that walked the whole yard; the two are registered by cross-correlation and
the human stitch is kept where both cover a pixel.

The correlation is computed on the frame with a mask: the rows of the status
strip and any dialogue box (a white text run over a black panel) are left out,
and a frame that correlates below MIN_NCC or whose masked area exceeds a third
of the frame (a menu, a fight screen) is skipped. The fence and the walls
repeat, so a match is only accepted within MAX_JUMP px of the last placed
frame, and a frame that repeats the one before it, while the model thinks, is
not placed again. The hero is located as in the hybrid mode of
human/route.py: the scene scrolls to keep him on his tile, so while the view
moves between placed frames he stands on the spawn tile of the frame, and
while the view is clamped at a border of the scene he is the densest 24x40
block of pixels that differ from the panorama, from which he was removed,
kept within 60 px of his last screen position. His place on the compound is
the offset of the frame plus his
screen position. The path is smoothed by a running mean of three and saved as
a .npy beside the picture; route_panel.py draws the figure panels from it,
and the .txt stamp names the session.
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

W0, H0 = 320, 200
R0, R1 = 8, 192
PANO = os.path.join(HERE, "compound.png")
SPAWN = (146, 78)          # the spawn tile in the first frame, as in human/route.py
MIN_NCC = 0.55
MAX_JUMP = 120         # px the view may move between placed frames; a match farther away is discarded
DIALOGUE_WHITE, DIALOGUE_BLACK = 300, 800   # as in model_route.py


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


def dialogue_mask(f):
    """True over a dialogue box: its white text and black panel, grown to cover the box."""
    white = f.min(axis=2) > 225
    black = f.max(axis=2) < 20
    if white.sum() <= DIALOGUE_WHITE or black.sum() <= DIALOGUE_BLACK:
        return np.zeros(f.shape[:2], bool)
    ys, xs = np.where(black)
    m = np.zeros(f.shape[:2], bool)
    y0, y1 = max(0, ys.min() - 4), min(H0, ys.max() + 5)
    x0, x1 = max(0, xs.min() - 4), min(W0, xs.max() + 5)
    m[y0:y1, x0:x1] = True
    return m


def masked_ncc_map(img, valid, t, keep):
    """normalised cross-correlation of t at every position of img over the pixels
    where keep (in t) and valid (in img) both hold, through the FFT."""
    h, w = t.shape
    k = keep.astype(np.float32)
    kf = np.fft.rfft2(k[::-1, ::-1], s=img.shape)
    v = valid.astype(np.float32)
    iv = img * v

    def corr(a, b):
        return np.fft.irfft2(np.fft.rfft2(a) * b, s=img.shape)[h - 1:, w - 1:]

    n = corr(v, kf)                                  # pixels counted
    tk = t * k
    s_t = corr(v, np.fft.rfft2(tk[::-1, ::-1], s=img.shape))
    s_tt = corr(v, np.fft.rfft2((tk * t)[::-1, ::-1], s=img.shape))
    s_i = corr(iv, kf)
    s_ii = corr(iv * img, kf)
    s_it = corr(iv, np.fft.rfft2(tk[::-1, ::-1], s=img.shape))
    n = np.maximum(n, 1.0)
    cov = s_it - s_i * s_t / n
    var_i = s_ii - s_i * s_i / n
    var_t = s_tt - s_t * s_t / n
    den = np.sqrt(np.maximum(var_i, 1.0) * np.maximum(var_t, 1.0))
    ncc = cov / den
    ncc[n < 0.6 * h * w] = -1.0                      # the frame must lie mostly on the panorama
    return ncc


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
    valid = pano.sum(axis=2) > 0
    path, placed, skipped = [], 0, 0
    screen, last_off, last_f = SPAWN, None, None
    for i, f in enumerate(frames(video, ev["first_black_second"])):
        # the replay holds a frame while the model thinks; a repeat adds nothing
        if last_f is not None and (np.abs(f.astype(np.int16) - last_f.astype(np.int16)).max(axis=2) > 30)[R0:R1].sum() < 30:
            continue
        last_f = f
        g = f.astype(np.float32).mean(axis=2)
        keep = ~dialogue_mask(f)
        keep[:R0] = False
        keep[R1:] = False
        if keep.mean() < 0.6:
            skipped += 1
            continue
        m = masked_ncc_map(pg, valid, g, keep)
        if last_off is not None:
            # the view moves a few tiles between frames; a match far from the last
            # offset is a repeated pattern of fence or wall, not the hero's place
            yy, xx = np.mgrid[0:m.shape[0], 0:m.shape[1]]
            m = np.where((np.abs(xx - last_off[0]) > MAX_JUMP) | (np.abs(yy - last_off[1]) > MAX_JUMP), -1.0, m)
        y, x = np.unravel_index(np.argmax(m), m.shape)
        if m[y, x] < MIN_NCC:
            skipped += 1
            continue
        placed += 1
        moved = last_off is not None and (x, y) != last_off
        last_off = (x, y)
        if moved:
            # the scene scrolls to keep the hero on his tile, so while the view
            # moves he stands on the spawn tile of the frame, as in the hybrid
            # mode of human/route.py; only at a border, where the view is clamped,
            # does the sprite move across the screen and is tracked below
            screen = SPAWN
        else:
            region = pg[y:y + H0, x:x + W0]
            d = (np.abs(g - region) > 40) & keep & valid[y:y + H0, x:x + W0]
            if d.sum() >= 40 and d.mean() < 0.2:
                c = np.pad(d.astype(np.float32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
                bh, bw = 40, 24
                s_ = c[bh:, bw:] - c[:-bh, bw:] - c[bh:, :-bw] + c[:-bh, :-bw]
                yy, xx = np.mgrid[0:s_.shape[0], 0:s_.shape[1]]
                far = (np.abs(xx + bw / 2 - screen[0]) > 60) | (np.abs(yy + bh * 0.75 - screen[1]) > 60)
                s_ = np.where(far, 0, s_)
                by, bx = np.unravel_index(np.argmax(s_), s_.shape)
                if s_[by, bx] >= 60:
                    screen = (bx + bw / 2, by + bh * 0.75)
        path.append((x + screen[0], y + screen[1]))
    print(sid, row["agent"], "frames placed", placed, "skipped", skipped, "path points", len(path))
    # a running mean of three, as in human/route.py
    if len(path) > 4:
        path = [path[0]] + [((a[0] + p[0] + b[0]) / 3, (a[1] + p[1] + b[1]) / 3)
                            for a, p, b in zip(path, path[1:], path[2:])] + [path[-1]]
    np.save(out[:-4] + "-path.npy", np.array(path, np.float32))
    import route_panel
    route_panel.draw(np.array(path, np.float64), out)
    with open(out[:-4] + ".txt", "w") as fh:
        fh.write(sid + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
