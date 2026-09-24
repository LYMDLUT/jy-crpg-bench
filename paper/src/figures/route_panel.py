"""Draw one panel of the route figure: a path over the panorama of the opening
compound, in the style shared by all model panels.

    python route_panel.py <path.npy> <out.png> [--legend]

The panorama is compound.png in this directory (see compound_panorama.py).
Pixels it never covered are black in that file and become white here, so the
compound sits on the page without a ragged dark border; the picture is cropped
to the covered area and upscaled by SCALE with nearest-neighbour sampling so
the pixel art stays crisp. The path is smoothed by a short running mean and
coloured by its progress from the spawn tile (yellow) to the gate (dark red),
so a walk that crosses the yard several times can still be read in order, and
a thin white halo keeps it visible over the fence and the floor. The circle
marks the first point and the square the last, as in human/route.py.
--legend adds a small progress bar in the empty lower-left corner.
"""
import os
import sys

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PANO = os.path.join(HERE, "compound.png")
SCALE = 2                      # nearest-neighbour upscale of the pixel art
PAD = 6                        # panorama pixels of white around the compound
FADE = 0.18                    # how far the panorama is pulled towards white, so the path reads first
CMAP = LinearSegmentedColormap.from_list("route", ["#ffd23f", "#ff7f11", "#e3242b", "#7a0c14"])


def smooth(path, k=5):
    """Running mean over k points; the ends stay where they are."""
    if len(path) < k + 2:
        return path
    h = k // 2
    out = [path[0]]
    for i in range(1, len(path) - 1):
        out.append(path[max(0, i - h):i + h + 1].mean(axis=0))
    out.append(path[-1])
    return np.array(out)


def draw(path, out, legend=False):
    path = smooth(np.asarray(path, np.float64))

    pano = np.asarray(Image.open(PANO).convert("RGB"), np.float32)
    covered = pano.sum(axis=2) > 0
    ys, xs = np.where(covered)
    y0, y1 = max(0, ys.min() - PAD), min(pano.shape[0], ys.max() + 1 + PAD)
    x0, x1 = max(0, xs.min() - PAD), min(pano.shape[1], xs.max() + 1 + PAD)
    crop = pano[y0:y1, x0:x1] * (1 - FADE) + 255 * FADE
    crop[~covered[y0:y1, x0:x1]] = 255
    crop = crop.clip(0, 255).astype(np.uint8)
    big = np.asarray(Image.fromarray(crop).resize(((x1 - x0) * SCALE, (y1 - y0) * SCALE), Image.NEAREST))

    w, h = big.shape[1], big.shape[0]
    fig = plt.figure(figsize=(w / 300, h / 300), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(big, interpolation="nearest")
    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(h - 0.5, -0.5)
    ax.axis("off")

    pts = (path - [x0, y0]) * SCALE
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    t = np.linspace(0, 1, len(segs))
    ax.add_collection(LineCollection(segs, colors="white", linewidths=3.4, alpha=0.9,
                                     capstyle="round", joinstyle="round", zorder=2))
    lc = LineCollection(segs, cmap=CMAP, linewidths=1.7, capstyle="round", joinstyle="round", zorder=3)
    lc.set_array(t)
    lc.set_clim(0, 1)
    ax.add_collection(lc)

    (sx, sy), (ex, ey) = pts[0], pts[-1]
    ax.scatter([sx], [sy], s=46, marker="o", c=[CMAP(0.0)], edgecolors="white", linewidths=1.3, zorder=5)
    ax.scatter([ex], [ey], s=46, marker="s", c=[CMAP(1.0)], edgecolors="white", linewidths=1.3, zorder=5)

    if legend:
        cax = fig.add_axes([0.04, 0.07, 0.20, 0.022])
        cax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=CMAP, extent=[0, 1, 0, 1])
        cax.set_xticks([])
        cax.set_yticks([])
        for s in cax.spines.values():
            s.set_edgecolor("white")
            s.set_linewidth(0.8)
        cax.text(0, 1.4, "spawn", fontsize=5.5, ha="left", va="bottom", color="#333333", transform=cax.transAxes)
        cax.text(1, 1.4, "gate", fontsize=5.5, ha="right", va="bottom", color="#333333", transform=cax.transAxes)

    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)
    # the pixel art and the path together use few colours; a palette PNG is a third the size
    Image.open(out).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                                            dither=Image.Dither.NONE).save(out, optimize=True)
    return (w, h), len(path)


def main():
    path_file, out = sys.argv[1], sys.argv[2]
    size, n = draw(np.load(path_file), out, legend="--legend" in sys.argv[3:])
    print("wrote", out, size, "path points", n)


if __name__ == "__main__":
    main()
