"""The world map of the game at native scale, rendered from its data files.

    python worldmap.py            # writes worldmap.png and worldmap.json

The map is 480 x 480 tiles. EARTH, SURFACE and BUILDING hold one 16-bit picture
number per tile (twice the index into MMAP.GRP), BUILDX and BUILDY name the
anchor tile of the building that covers a tile, and MMAP.COL is the 6-bit
palette. A tile (x, y) is drawn with its centre at ((y - x) * 18, (x + y) * 9)
from the map origin, as the game draws it, ground and surface first and then
the buildings from the back row to the front. Each picture is run-length
coded: width, height, x and y offset, then per row a byte count followed by
(skip, n, n palette indices) runs. worldmap.json records the pixel of tile
(0, 0) so that a pixel converts back to a tile.
"""
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "..", "..", "..", "game")
N = 480
TW, TH = 18, 9


def grid(name):
    return np.fromfile(os.path.join(GAME, name), "<i2").reshape(N, N).astype(np.int32)


def pictures():
    idx = np.fromfile(os.path.join(GAME, "MMAP.IDX"), "<i4")
    grp = open(os.path.join(GAME, "MMAP.GRP"), "rb").read()
    pal = np.fromfile(os.path.join(GAME, "MMAP.COL"), np.uint8).reshape(256, 3).astype(np.uint16) * 4
    starts = np.concatenate([[0], idx[:-1]])
    cache = {}

    def pic(n):
        if n in cache:
            return cache[n]
        o, end = int(starts[n]), int(idx[n])
        if end - o < 8:
            cache[n] = None
            return None
        w, h, xs, ys = (int(v) for v in np.frombuffer(grp[o:o + 8], "<i2"))
        if w <= 0 or h <= 0:
            cache[n] = None
            return None
        rgba = np.zeros((h, w, 4), np.uint8)
        p = o + 8
        for row in range(h):
            n_bytes = grp[p]
            p += 1
            stop = p + n_bytes
            x = 0
            while p < stop:
                x += grp[p]
                cnt = grp[p + 1]
                px = np.frombuffer(grp[p + 2:p + 2 + cnt], np.uint8)
                if cnt and x + cnt <= w and h > 0:
                    rgba[row, x:x + cnt, :3] = pal[px].clip(0, 255)
                    rgba[row, x:x + cnt, 3] = 255
                x += cnt
                p += 2 + cnt
        cache[n] = (rgba, int(xs), int(ys))
        return cache[n]
    return pic


def render():
    earth, surface, building = grid("EARTH.002") // 2, grid("SURFACE.002") // 2, grid("BUILDING.002") // 2
    pic = pictures()
    margin_x, margin_y = N * TW + 64, 160
    W, H = 2 * N * TW + 128, 2 * N * TH + 320
    img = np.zeros((H, W, 3), np.uint8)

    def blit(n, cx, cy):
        got = pic(n)
        if got is None:
            return
        rgba, xs, ys = got
        h, w = rgba.shape[:2]
        x0, y0 = cx - xs, cy - ys
        if x0 < 0 or y0 < 0 or x0 + w > W or y0 + h > H:
            return
        a = rgba[:, :, 3:] > 0
        dst = img[y0:y0 + h, x0:x0 + w]
        np.copyto(dst, rgba[:, :, :3], where=a)

    def centre(x, y):
        return margin_x + (y - x) * TW, margin_y + (x + y) * TH

    for s in range(2 * N - 1):
        for x in range(max(0, s - N + 1), min(N, s + 1)):
            y = s - x
            cx, cy = centre(x, y)
            if earth[x, y]:
                blit(earth[x, y], cx, cy)
            if surface[x, y]:
                blit(surface[x, y], cx, cy)
    for s in range(2 * N - 1):
        for x in range(max(0, s - N + 1), min(N, s + 1)):
            y = s - x
            if building[x, y]:
                blit(building[x, y], *centre(x, y))
    return img, {"origin": [margin_x, margin_y], "tile": [TW, TH], "size": [W, H]}


def to_tile(px, py, meta):
    """Pixel on worldmap.png to the tile (x, y) whose centre is nearest."""
    u = (px - meta["origin"][0]) / TW       # y - x
    v = (py - meta["origin"][1]) / TH       # x + y
    return (v - u) / 2, (v + u) / 2


def main():
    img, meta = render()
    Image.fromarray(img).save(os.path.join(HERE, "worldmap.png"))
    json.dump(meta, open(os.path.join(HERE, "worldmap.json"), "w"), indent=1)
    print("wrote worldmap.png", img.shape)


if __name__ == "__main__":
    main()
