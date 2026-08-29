"""Figures for the paper, from the published catalogue numbers."""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

plt.rcParams.update({
    "font.family": "serif", "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 200,
})

# agent, actions, meaningful ratio, oscillation, ttfa, gap_p50, gap_p95,
# distinct keys, reads, played
RUNS = [
    ("claude-opus-5",     114, 0.842, 0.026,  18.9,  6.3,  26.7, 10,  77, 1167),
    ("Qwen3.8-27B",        48, 0.854, 0.062,  17.7,  7.6, 107.0,  5,  50, 1096),
    ("claude-sonnet-5",    51, 0.824, 0.020,  11.7, 21.4,  43.6,  5,  51, 1160),
    ("claude-fable-5",    159, 0.748, 0.006,  18.6,  5.1,  18.0,  8, 126, 1182),
    ("grok-4.6",          116, 0.655, 0.069,  18.5,  8.7,  24.9,  8, 100, 1168),
    ("random",            720, 0.403, 0.065,   0.5,  1.4,   3.7, 13,   0, 1200),
    ("gemini-3.7-flash",  337, 0.068, 0.018, 219.5,  1.6,   2.1,  7, 333, 1200),
]

def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), p, min(1, c + h)

# ------------------------------------------------ fig: quality vs throughput
fig, ax = plt.subplots(figsize=(5.0, 3.1))
pts = []
for name, n, ratio, *_ in RUNS:
    k = round(ratio * n)
    lo, p, hi = wilson(k, n)
    pts.append((name, k, p, lo, hi))
front = [q for q in pts if not any(o[1] > q[1] and o[2] > q[2] for o in pts)]
front.sort(key=lambda q: q[1])
ax.plot([q[1] for q in front], [q[2] for q in front], "--", lw=0.9,
        color="0.25", zorder=1)
for name, k, p, lo, hi in pts:
    on = any(f[0] == name for f in front)
    ax.errorbar(k, p, yerr=[[p - lo], [hi - p]], fmt="o",
                ms=5 if on else 4, color="0.1" if on else "0.62",
                ecolor="0.75", elinewidth=0.8, capsize=2, zorder=3)
    dx, dy, ha = 7, 0, "left"
    if name == "random": dx, dy, ha = -9, 0.015, "right"
    if name == "Qwen3.8-27B": dy = 0.045
    if name == "claude-sonnet-5": dy = -0.062
    if name == "claude-opus-5": dy = 0.012
    ax.annotate(name, (k, p), xytext=(dx, dy * 300), textcoords="offset points",
                ha=ha, va="center", fontsize=8,
                color="0.1" if on else "0.45")
ax.set_xlabel("meaningful actions (throughput)")
ax.set_ylabel("meaningful step ratio (quality)")
ax.set_ylim(0, 1.0)
ax.set_xlim(0, 330)
fig.tight_layout()
fig.savefig("pareto.pdf")
plt.close(fig)

# ------------------------------------------------ fig: behavioural signatures
fig, axes = plt.subplots(1, 3, figsize=(5.6, 2.1))
names = [r[0] for r in RUNS]
short = [n.replace("claude-", "c-").replace("gemini-", "g-")
          .replace("Qwen3.8-27B", "qwen3.8") for n in names]
order = list(range(len(RUNS)))

looks = [r[8] / r[1] for r in RUNS]
axes[0].barh(order, looks, color="0.35", height=0.62)
axes[0].set_title("screen reads / action", fontsize=8)
axes[0].set_yticks(order, short, fontsize=7)
axes[0].invert_yaxis()

p50 = [r[5] for r in RUNS]
axes[1].barh(order, p50, color="0.35", height=0.62)
axes[1].set_title("think time p50 (s)", fontsize=8)
axes[1].set_yticks(order, ["" for _ in order])
axes[1].invert_yaxis()

apm = [r[1] / (r[9] / 60) for r in RUNS]
axes[2].barh(order, apm, color="0.35", height=0.62)
axes[2].set_title("actions / minute", fontsize=8)
axes[2].set_yticks(order, ["" for _ in order])
axes[2].invert_yaxis()
for a in axes:
    a.tick_params(axis="x", labelsize=7)
fig.tight_layout()
fig.savefig("behaviour.pdf")
plt.close(fig)

# ------------------------------------------------ fig: milestone ladder
LADDER = ["acted", "screen\nresponded", "picked\nsomething up",
          "gained\nexperience", "left opening\nscene", "reached\nlevel 2"]
# 1 reached, 0 not reached, None unmeasured (run predates instrumentation)
STATUS = {
    "claude-opus-5":    [1, 1, None, None, None, None],
    "Qwen3.8-27B":      [1, 1, None, None, None, None],
    "claude-sonnet-5":  [1, 1, None, None, None, None],
    "claude-fable-5":   [1, 1, None, None, None, None],
    "grok-4.6":         [1, 1, None, None, None, None],
    "random":           [1, 1, 0, 0, 0, 0],
    "gemini-3.7-flash": [1, 1, None, None, None, None],
}
fig, ax = plt.subplots(figsize=(5.2, 2.3))
for yi, name in enumerate(names):
    for xi, v in enumerate(STATUS[name]):
        if v == 1:
            ax.scatter(xi, yi, s=64, color="0.1", zorder=3)
        elif v == 0:
            ax.scatter(xi, yi, s=52, facecolors="white", edgecolors="0.55",
                       linewidths=1.1, zorder=3)
        else:
            ax.scatter(xi, yi, s=52, facecolors="0.93", edgecolors="0.8",
                       linewidths=0.9, linestyle=":", zorder=3)
ax.set_yticks(range(len(names)), short, fontsize=8)
ax.set_xticks(range(len(LADDER)), LADDER, fontsize=7)
ax.invert_yaxis()
ax.set_xlim(-0.5, len(LADDER) - 0.5)
ax.spines["left"].set_visible(False)
ax.spines["bottom"].set_visible(False)
ax.tick_params(length=0)
ax.axvline(1.5, color="0.85", lw=16, zorder=1, alpha=0.5)
handles = [
    Line2D([], [], marker="o", ls="", color="0.1", ms=7, label="reached"),
    Line2D([], [], marker="o", ls="", markerfacecolor="white",
           markeredgecolor="0.55", ms=7, label="not reached"),
    Line2D([], [], marker="o", ls="", markerfacecolor="0.93",
           markeredgecolor="0.8", ms=7, label="unmeasured"),
]
ax.legend(handles=handles, loc="upper right", fontsize=7, frameon=False,
          bbox_to_anchor=(1.02, 1.18), ncol=3)
fig.tight_layout()
fig.savefig("ladder.pdf")
plt.close(fig)
print("wrote pareto.pdf behaviour.pdf ladder.pdf")
