"""Cross-check a random-baseline run: what the script drew against what the
emulator was given.

    python3 bench/check_random_run.py <timeline.json> [--seed 1996] [--catalog catalog.json]

The baseline is seeded, so its whole key sequence can be recomputed offline:
one ``choice`` per action and one ``expovariate`` per successful action, in
that order. The timeline sidecar the run publishes is written from the
recording journal, which logs every key the server pressed on the core and
for how long. The two must agree key for key; the catalogue entry, when given,
must agree in its histogram and its event count.
"""
import argparse
import collections
import json
import random
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from random_baseline import ACTIONS  # noqa: E402


def intended(seed, n, pace):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(rng.choice(ACTIONS))
        rng.expovariate(1 / pace)
    return out


def load(path_or_url):
    if path_or_url.startswith("http"):
        return json.load(urllib.request.urlopen(path_or_url, timeout=60))
    return json.load(open(path_or_url, encoding="utf-8"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("timeline")
    p.add_argument("--seed", type=int, default=1996)
    p.add_argument("--pace", type=float, default=1.1)
    p.add_argument("--catalog")
    p.add_argument("--fps", type=float, default=70.086)
    a = p.parse_args()

    tl = load(a.timeline)
    marks = tl["marks"]
    sent = [k for m in marks for k, _ in m.get("keys", [])]
    holds = [h for m in marks for _, h in m.get("keys", [])]
    want = intended(a.seed, len(sent), a.pace)
    diffs = [(i + 1, w, s) for i, (w, s) in enumerate(zip(want, sent)) if w != s]
    print(f"run {tl.get('id')} ({tl.get('agent')}): {len(marks)} actions, {len(sent)} key events")
    print(f"seeded sequence vs journal: {len(sent) - len(diffs)}/{len(sent)} keys agree"
          + (f"; first differences {diffs[:5]}" if diffs else ""))
    verbs = collections.Counter(m["do"].split()[0] for m in marks)
    print("verbs in the journal:", dict(verbs))
    frames = [h * a.fps for h in holds]
    print(f"hold per key: {min(holds):.3f}-{max(holds):.3f} s = {min(frames):.1f}-{max(frames):.1f} frames"
          f" (requested 10; the journal stamps on frame boundaries)")
    if a.catalog:
        runs = load(a.catalog)
        row = next((r for r in runs if r.get("id") == tl.get("id")), None)
        if row is None:
            print("catalogue: no entry with this id")
        else:
            hist = collections.Counter(sent)
            same = dict(row.get("keys") or {}) == dict(hist)
            print(f"catalogue histogram {'matches' if same else 'DIFFERS from'} the journal;"
                  f" key_events {row.get('key_events')} vs {len(sent)} in the journal;"
                  f" actions {row.get('actions')} vs {len(marks)} marks")
            if not same:
                print("  catalogue:", dict(sorted((row.get("keys") or {}).items())))
                print("  journal:  ", dict(sorted(hist.items())))
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
