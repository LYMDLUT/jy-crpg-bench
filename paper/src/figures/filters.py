"""The filters: every model session (hour and four-hour) along the chain of
steps a playthrough passes in order.

    python filters.py

Left, the share of sessions that passed each step. Right, per step, the
minutes from the step before to passing it (filled) or, for a session that
did not pass it, to its last key (open).
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import field  # noqa: E402

INK = "#1c1c1e"
plt.rcParams.update({"font.family": "serif", "font.size": 7.5})


def rows():
    return [r for r in field.played(field.load_runs(dedup=False)) if not field.is_random(r["agent"])] + field.load_long()


def main():
    ch = field.chain(rows())
    n = len(rows())
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 1.55), gridspec_kw={"width_ratios": [1, 1.25], "wspace": 0.28})
    xs = list(range(len(ch)))
    share = [len(s["passed"]) / n for s in ch]
    a.bar(xs, share, width=0.62, color="#d6d9df", edgecolor=INK, linewidth=0.6)
    for x, s, v in zip(xs, ch, share):
        a.text(x, v + 0.03, "%d" % len(s["passed"]), ha="center", fontsize=7, color=INK)
    a.set_xticks(xs)
    a.set_xticklabels([s["step"] for s in ch], fontsize=6.2)
    a.set_ylim(0, 1.0)
    a.set_ylabel("share of %d sessions" % n, color=INK)
    b.set_yscale("log")
    # the two models that pass the filters in colour, every other model in grey;
    # the grey sessions that pass a filter are named beside their dot
    top = {"claude-opus-5.5": "#2F6FB0", "gpt-6-astra": "#C8632A"}
    filters = {"reach\nhermit", "win\nbattle"}
    for x, s in zip(xs, ch):
        for kind, off, pts in (("passed", -0.12, s["passed"]), ("stuck", 0.12, s["stuck"])):
            for r, d in pts:
                c = top.get(r["agent"], "#8a8d93")
                b.scatter([x + off], [max(d, 0.5)], s=10, zorder=3, linewidths=0.7,
                          color=c if kind == "passed" else "none", edgecolors=c)
    b.axhline(30, color="#8a8d93", lw=0.6, ls=(0, (2, 2)))
    b.set_ylim(0.35, 400)
    # the grey sessions that pass a filter, named in a callout in the empty lower right
    import collections
    import math
    for x, s in zip(xs, ch):
        if s["step"] not in filters:
            continue
        grey = [(r, d) for r, d in s["passed"] if r["agent"] not in top]
        if not grey:
            continue
        n = collections.Counter(r["agent"] for r, _ in grey)
        names = ", ".join("%s%s" % (a_, " (%d)" % k if k > 1 else "") for a_, k in sorted(n.items()))
        yc = math.exp(sum(math.log(d) for _, d in grey) / len(grey))
        tx, ty = 4.34, 1.45
        b.annotate("", xy=(x - 0.18, yc), xytext=(tx - 0.05, ty), arrowprops=dict(arrowstyle="-", color=INK, lw=0.5, shrinkA=0, shrinkB=0))
        b.text(tx, ty, "also reached the hermit:\n" + names.replace(", ", "\n"), fontsize=5.4, color=INK, va="center", ha="left", linespacing=1.15)
    b.set_xticks(list(xs))
    b.set_xticklabels([s["step"] for s in ch], fontsize=6.2)
    b.set_ylabel("minutes since the step before", color=INK)
    for name, c in list(top.items()) + [("other models", "#8a8d93")]:
        b.scatter([], [], s=10, color=c, label=name)
    b.scatter([], [], s=10, color="none", edgecolors=INK, linewidths=0.7, label="not passed")
    b.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, fontsize=6, frameon=False, handletextpad=0.1, columnspacing=0.8)
    for ax in (a, b):
        ax.tick_params(colors=INK, labelsize=6.5)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    fig.savefig(os.path.join(HERE, "filters.pdf"), bbox_inches="tight", pad_inches=0.02)
    print("wrote filters.pdf")


if __name__ == "__main__":
    main()
