#!/usr/bin/env python3
"""Play a full run by drawing keys out of a hat.

The point of a random baseline is to say what a score means. A metric that a
coin flip can saturate is measuring the game, not the player, so every number
the catalogue reports should be read against this line. The literature runs
one for the same reason: lmgame-Bench (2505.15146) treats random play as the
floor a model has to clear before its score says anything.

There is no model here and no screen reading. It picks from the same key
vocabulary the brief teaches an agent, at a cadence in the range agents
actually achieve, and stops when the server says the run is over.

    uv run bench/random_baseline.py --minutes 20
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

BACKEND = "https://jy-crpg-bench-366646433082.us-central1.run.app"

# Weighted the way the brief presents them rather than uniformly: movement is
# most of what the game asks for, enter advances anything with text in it, and
# the rest are there so the action histogram is not artificially narrow. A
# uniform draw over every key would spend most of the run typing letters at a
# world map, which understates the floor rather than measuring it.
ACTIONS = (["kp1", "kp3", "kp7", "kp9"] * 8 +
           ["enter"] * 6 + ["space"] * 2 + ["escape"] * 2 +
           ["y", "n"] + ["up", "down", "left", "right"])


def call(url, body=None, timeout=60, tries=4):
    """One request, retried through the network being briefly unavailable.

    A single timed-out connection used to end the whole run: the script died,
    nothing sent another key, and the server tore the session down as idle
    twelve minutes short. The baseline is meant to measure the game, not the
    link to it.
    """
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(
            url, data=data, method="POST" if data else "GET",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {}
        except Exception as exc:
            if attempt == tries - 1:
                print(f"  giving up on {url}: {exc}", flush=True)
                return 0, {}
            time.sleep(1.5 * (attempt + 1))
    return 0, {}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", default=BACKEND)
    p.add_argument("--minutes", type=int, default=20)
    p.add_argument("--name", default="random-baseline")
    p.add_argument("--seed", type=int, default=1996)
    # A model spends real time thinking between keys. Matching that cadence
    # keeps the comparison about what is pressed rather than how fast.
    p.add_argument("--pace", type=float, default=1.1,
                   help="mean seconds between actions")
    a = p.parse_args()

    rng = random.Random(a.seed)
    status, s = call(f"{a.backend}/session",
                     {"agent": a.name, "minutes": a.minutes})
    if status != 200 or "base_url" not in s:
        raise SystemExit(f"could not start a run: {status} {s}")
    base = s["base_url"]
    print(f"  {s.get('session_id', '?')}  {s.get('seconds', '?')}s  {base}",
          flush=True)

    started, n, hist = time.time(), 0, {}
    while True:
        key = rng.choice(ACTIONS)
        status, r = call(f"{base}/api/key", {"key": key})
        if status == 410 or r.get("ended"):
            print(f"\n  ended: {r.get('reason', '?')}  after {n} actions",
                  flush=True)
            if r.get("video_url"):
                print(f"  video: {r['video_url']}", flush=True)
            return
        if status != 200:
            print(f"  {status} on {key}: {r}", flush=True)
            time.sleep(2)
            continue
        n += 1
        hist[key] = hist.get(key, 0) + 1
        if n % 100 == 0:
            _, st = call(f"{base}/status")
            sess = st.get("session", {})
            mins = (time.time() - started) / 60
            print(f"  {n:5} actions  {mins:5.1f}m  places {sess.get('places')}"
                  f"  left {sess.get('remaining', '?')}", flush=True)
        time.sleep(rng.expovariate(1 / a.pace))


if __name__ == "__main__":
    main()
