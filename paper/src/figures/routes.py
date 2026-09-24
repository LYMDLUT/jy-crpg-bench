"""The route figures: every model in the opening compound, and three sessions on
the world map, each path coloured by the minute of play.

    python routes.py

routes-compound.pdf has one panel per model, in the order of the upper panel of
Figure 3, with the path of its reported session from the spawn tile to the
first black frame, read by anchored_route.py into routes/compound-<id>.json.
routes-world.pdf has the world-map walks read by worldmap_route.py into
routes/world-<id>.json: the gpt-6-astra session that entered the most distinct
scenes, the claude-opus-5.5 session reported in Figure 3, and the session that
spent longest on the world map without entering a scene. Scene entries and the
replay panels (hermit, compass, fight, defeat, recruitment) are marked where
the hero stood on the world map just before them. Both figures share one
colour scale of 0 to 60 minutes; arrowheads along the path give its direction.
"""
import json
import os
import sys

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import field  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
plt.rcParams.update({"font.family": "serif", "font.size": 7})
INK = "#1c1c1e"
# one hue, light to dark, absent from both the compound and the world map
CMAP = LinearSegmentedColormap.from_list("minute", ["#e98fe6", "#b54fc9", "#6f1f93", "#2a0544"])
NORM = Normalize(0, 60)
FADE = 0.35                    # the picture is pulled towards white so the path reads first


def load(kind, sid):
    d = json.load(open(os.path.join(HERE, "routes", f"{kind}-{sid}.json"), encoding="utf-8"))
    return np.array(d["rows"], np.float64)


def faded(img):
    a = np.asarray(img.convert("RGB"), np.float32)
    return (a * (1 - FADE) + 255 * FADE).clip(0, 255).astype(np.uint8)


def draw_path(ax, xy, t, lw=1.2, arrows=6, gaps=None):
    """The path in segments coloured by minute over a white halo, with an
    arrowhead every len/arrows segments. A segment longer than `gaps` px is a
    jump (a scene, a loaded save) and is left out."""
    segs = np.stack([xy[:-1], xy[1:]], axis=1)
    tm = (t[:-1] + t[1:]) / 2
    if gaps is not None:
        ok = np.hypot(*(xy[1:] - xy[:-1]).T) <= gaps
        segs, tm = segs[ok], tm[ok]
    ax.add_collection(LineCollection(segs, colors="white", linewidths=lw + 1.4, capstyle="round", zorder=2))
    lc = LineCollection(segs, cmap=CMAP, norm=NORM, linewidths=lw, capstyle="round", zorder=3)
    lc.set_array(tm)
    ax.add_collection(lc)
    d = np.hypot(*(segs[:, 1] - segs[:, 0]).T)
    cum = np.cumsum(d)
    if cum[-1] > 0:
        for k in range(1, arrows + 1):
            i = int(np.searchsorted(cum, cum[-1] * k / (arrows + 1)))
            i = min(i, len(segs) - 1)
            (x0, y0), (x1, y1) = segs[i]
            if np.hypot(x1 - x0, y1 - y0) < 1e-6:
                continue
            ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=4,
                        arrowprops=dict(arrowstyle="-|>,head_length=0.55,head_width=0.32", lw=0,
                                        color=CMAP(NORM(tm[i])), shrinkA=0, shrinkB=0))
    ax.scatter([xy[0, 0]], [xy[0, 1]], s=14, marker="o", color=CMAP(NORM(t[0])), edgecolors="white", linewidths=0.8, zorder=5)
    ax.scatter([xy[-1, 0]], [xy[-1, 1]], s=14, marker="s", color=CMAP(NORM(t[-1])), edgecolors="white", linewidths=0.8, zorder=5)


def colorbar(fig, rect):
    cax = fig.add_axes(rect)
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=NORM, cmap=CMAP), cax=cax, orientation="horizontal")
    cb.set_ticks([0, 10, 20, 30, 40, 50, 60])
    cb.outline.set_linewidth(0.4)
    cax.tick_params(labelsize=6, length=2, width=0.4)
    cb.set_label("minute of play", fontsize=6.5, labelpad=1)


def compound_figure():
    rows = field.played(field.load_runs(dedup=False))
    models = [m for m in field.model_rows([r for r in rows if not field.is_random(r["agent"])])]
    models.sort(key=field.ladder_order)
    reported = {r["agent"]: r for r in field.best_per_model(rows)}
    paths = {m["agent"]: load("compound", reported[m["agent"]]["id"]) for m in models}
    pano = Image.open(os.path.join(HERE, "compound.png"))
    cov = np.asarray(pano.convert("L")) > 0
    bg = faded(pano)
    bg[~cov] = 255
    # the crop is the extent of every walk with a margin, so the panels show the
    # compound as large as the width allows
    allp = np.concatenate([p[:, :2] for p in paths.values()])
    pad = 30
    x0, x1 = max(0, int(allp[:, 0].min()) - pad), min(bg.shape[1], int(allp[:, 0].max()) + pad)
    y0, y1 = max(0, int(allp[:, 1].min()) - pad), min(bg.shape[0], int(allp[:, 1].max()) + pad)
    ncol, gap, head = 4, 0.05, 0.15
    nrow = -(-len(models) // ncol)
    w_in = 7.0
    pw = (w_in - gap * (ncol - 1)) / ncol
    ph = pw * (y1 - y0) / (x1 - x0)
    fig = plt.figure(figsize=(w_in, nrow * (ph + head)))
    H = fig.get_figheight()
    for k, m in enumerate(models):
        p = paths[m["agent"]]
        c, rr = k % ncol, k // ncol
        ax = fig.add_axes([c * (pw + gap) / w_in, (H - (rr + 1) * (ph + head)) / H, pw / w_in, ph / H])
        ax.imshow(bg[y0:y1, x0:x1], extent=(x0, x1, y1, y0), interpolation="nearest")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y1, y0)
        ax.axis("off")
        draw_path(ax, p[:, :2], p[:, 2], lw=1.0, arrows=5)
        ax.set_title(m["agent"], fontsize=6.5, pad=1.5, color=INK, family="monospace")
    fig.savefig(os.path.join(HERE, "routes-compound.pdf"), dpi=300)
    plt.close(fig)


# the scene banners the replay scan names, in English; the glossary gives the originals
SCENES = {"南賢居": "house of the hermit", "河洛客棧": "Heluo Inn", "高昇客棧": "Gaosheng Inn",
          "王居": "home", "閻基居": "house of Yan Ji", "田伯光居": "house of Tian Boguang",
          "藥王莊": "Yaowang Manor", "福威鏢局": "Fuwei Escort Agency", "峨嵋派": "Emei Sect"}
PANELS = ("hermit", "compass", "battle", "defeat")
PANEL_LABEL = {"hermit": "hermit", "compass": "compass read", "battle": "fight", "defeat": "fight lost"}
JUMP = 12 * 18                 # px: a longer step between placed frames is a scene or a loaded save
MERGE = 2 * 18                 # px: events this close share one marker


def world_sessions():
    """The three sessions of the world-map figure: the gpt-6-astra session that
    entered the most distinct scenes, the reported session of claude-opus-5.5,
    and the session that spent longest on the world map without a scene."""
    rows = field.played(field.load_runs(dedup=False))
    ev = json.load(open(os.path.join(HERE, "replay_events.json"), encoding="utf-8"))

    def distinct(r):
        return len({x["name"] for x in ev[r["id"]]["scenes"]["entries"] if x["name"] != "王居"})
    astra = max((r for r in rows if r["agent"] == "gpt-6-astra"), key=lambda r: (distinct(r), r["id"]))
    opus = next(r for r in field.best_per_model(rows) if r["agent"] == "claude-opus-5.5")
    crossed = [r for r in rows if r.get("exit_acts") is not None and not ev[r["id"]]["scenes"]["entries"]]
    orbit = max(crossed, key=lambda r: r["actions"] - r["exit_acts"])
    return [(r, ev[r["id"]]) for r in (astra, opus, orbit)]


def events(e, track):
    """The scene entries and replay panels of the hour, each at the last point on
    the world map before it, merged into one marker when they fall within
    MERGE px of each other: [(x, y, [(minute, label), ...]), ...] in order."""
    seen, out = set(), []
    for x in e["scenes"]["entries"]:
        if x["name"] != "王居" and x["name"] not in seen:
            seen.add(x["name"])
            out.append((x["minute"], SCENES[x["name"]]))
    out += [(e[n]["first_minute"], PANEL_LABEL[n]) for n in PANELS if e[n]["first_minute"] is not None]
    if e.get("recruited_minute") is not None:
        out.append((e["recruited_minute"], "companion"))
    marks = []
    for m, lab in sorted(out):
        before = track[track[:, 4] <= m]
        if not len(before) or m > 60:
            continue
        x, y = before[-1, 0], before[-1, 1]
        if marks and np.hypot(marks[-1][0] - x, marks[-1][1] - y) <= MERGE:
            marks[-1][2].append((m, lab))
        else:
            marks.append((x, y, [(m, lab)]))
    return marks


def smooth(xy, k=3):
    if len(xy) < k + 2:
        return xy
    out = xy.copy()
    for i in range(1, len(xy) - 1):
        out[i] = xy[max(0, i - k // 2):i + k // 2 + 1].mean(axis=0)
    return out


def world_figure():
    """Two by two: the three walks, and in the fourth cell the list of each
    walk's markers above the colour bar."""
    sess = world_sessions()
    tracks = [load("world", r["id"]) for r, _ in sess]
    pad = 36
    allp = np.concatenate(tracks)
    bx0, bx1 = int(allp[:, 0].min() - pad), int(allp[:, 0].max() + pad)
    by0, by1 = int(allp[:, 1].min() - pad), int(allp[:, 1].max() + pad)
    crop = faded(Image.open(os.path.join(HERE, "worldmap.png")).crop((bx0, by0, bx1, by1)))
    w_in, gap, head = 7.0, 0.12, 0.16
    pw = (w_in - gap) / 2
    ph = pw * (by1 - by0) / (bx1 - bx0)
    fig = plt.figure(figsize=(w_in, 2 * (ph + head) + gap))
    H = fig.get_figheight()
    cells = [(0, 0), (1, 0), (0, 1)]
    notes = []
    for ((r, e), t), (c, rr) in zip(zip(sess, tracks), cells):
        x = c * (pw + gap)
        y = H - (rr + 1) * (ph + head) - rr * gap
        ax = fig.add_axes([x / w_in, y / H, pw / w_in, ph / H])
        ax.imshow(crop, extent=(bx0, bx1, by1, by0), interpolation="nearest")
        ax.set_xlim(bx0, bx1)
        ax.set_ylim(by1, by0)
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_linewidth(0.4)
            sp.set_color(INK)
        draw_path(ax, smooth(t[:, :2]), t[:, 4], lw=1.2, arrows=9, gaps=JUMP)
        ax.set_title(r["agent"], fontsize=7.5, pad=2, color=INK, family="monospace")
        lines = []
        for i, (ex, ey, evs) in enumerate(events(e, t), 1):
            ax.scatter([ex], [ey], s=52, marker="o", color="white", edgecolors=INK, linewidths=0.7, zorder=6)
            ax.text(ex, ey, str(i), fontsize=5.6, ha="center", va="center", color=INK, zorder=7)
            lines.append("%d  %s" % (i, ", ".join("%s %d" % (lab, round(m)) for m, lab in evs)))
        notes.append((r["agent"], lines or ["no scene entered"]))
    # the fourth cell: the markers of each walk, then the colour bar
    x = pw + gap
    ty = H - (ph + head) - gap - head
    fig.text(x / w_in, ty / H, "Markers, with the minute of each event", fontsize=7, color=INK, va="top", style="italic")
    ty -= 0.2
    for agent, lines in notes:
        fig.text(x / w_in, ty / H, agent, fontsize=7.5, color=INK, family="monospace", va="top")
        ty -= 0.15
        for ln in lines:
            fig.text((x + 0.08) / w_in, ty / H, ln, fontsize=7, color=INK, va="top")
            ty -= 0.13
        ty -= 0.08
    colorbar(fig, [(x + 0.08) / w_in, (H - 2 * (ph + head) - gap + 0.24) / H, (pw - 0.5) / w_in, 0.08 / H])
    fig.savefig(os.path.join(HERE, "routes-world.pdf"), dpi=300)
    plt.close(fig)


def main():
    which = sys.argv[1:] or ["compound", "world"]
    if "compound" in which:
        compound_figure()
        print("wrote routes-compound.pdf")
    if "world" in which:
        world_figure()
        print("wrote routes-world.pdf")


if __name__ == "__main__":
    main()
