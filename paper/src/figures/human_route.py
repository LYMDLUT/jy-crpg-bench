"""The human route figure on one canvas: the world map between the two houses,
with the starting house and the house of the hermit set into its empty corners.

    python human_route.py

Reads route-compound.png, route-map.png and route-house.png, which human/route.py
writes from the speedrun, and writes route-human.pdf. The black outside each
panorama is turned white, as in the model route figures, and the two house
panels sit in the corners of the world map that the diagonal walk leaves empty:
the starting house at upper left, near where the walk begins, and the house of
the hermit at lower right, near where it ends. Each panel keeps its own scale.
"""
import os

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({"font.family": "serif", "font.size": 7})
INK = "#1c1c1e"


def whitened(name):
    a = np.asarray(Image.open(os.path.join(HERE, name)).convert("RGB")).copy()
    a[a.max(axis=2) == 0] = 255
    return a


def main():
    world, house, hermit = whitened("route-map.png"), whitened("route-compound.png"), whitened("route-house.png")
    Hw, Ww = world.shape[:2]
    w_in = 7.0
    h_in = w_in * Hw / Ww
    fig = plt.figure(figsize=(w_in, h_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(world, interpolation="nearest")
    ax.set_xlim(0, Ww)
    ax.set_ylim(Hw, 0)
    ax.axis("off")
    ax.text(0.5, 0.975, "(c)", transform=ax.transAxes, ha="center", va="top", fontsize=8, color=INK)

    def inset(img, x, y, w, label):
        # x, y, w in canvas pixels of the world map; the height follows the image
        h = w * img.shape[0] / img.shape[1]
        ia = fig.add_axes([x / Ww, 1 - (y + h) / Hw, w / Ww, h / Hw])
        ia.imshow(img, interpolation="nearest")
        ia.set_xticks([])
        ia.set_yticks([])
        for sp in ia.spines.values():
            sp.set_linewidth(0.5)
            sp.set_color(INK)
        ia.text(0.5, -0.02, label, transform=ia.transAxes, ha="center", va="top", fontsize=8, color=INK)

    inset(house, 32, 30, 640, "(a)")
    inset(hermit, Ww - 720 - 32, Hw - 720 * hermit.shape[0] / hermit.shape[1] - 54, 720, "(b)")
    fig.savefig(os.path.join(HERE, "route-human.pdf"), dpi=250)
    plt.close(fig)
    print("wrote route-human.pdf")


if __name__ == "__main__":
    main()
