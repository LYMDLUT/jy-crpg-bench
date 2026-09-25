"""A shell CLI with the MCP server's tools, for a harness without an MCP client.

DeepSeek Harness speaks ACP and drives a shell; it has no MCP client. Rather
than give it a different game, it gets the same two tools as a command:

    python cli.py guide            # the brief, the same text MCP sends as instructions
    python cli.py look             # the screen: text line + /tmp/screen.png
    python cli.py press kp3 kp3    # keys in order; --hold N frames

Same API, same benchmark profile, same counting on the server: a ``press`` is
one decision call whether it arrives through MCP or through this. The source
is kept here as a string so the task can upload it next to the MCP server
without the repository carrying two copies of the game knowledge.
"""

CLI_SOURCE = r'''#!/usr/bin/env python3
"""look / press / guide against the game API. See jy_crpg_nexus/dsh_cli.py."""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game_knowledge import adapt_guide

API = os.environ.get("QUNXIA_API", "http://127.0.0.1:8765").rstrip("/")
AGENT = "".join(c for c in os.environ.get("QUNXIA_AGENT", "dsh")
                if c.isascii() and (c.isalnum() or c in "-_."))[:40] or "dsh"
LANG = os.environ.get("QUNXIA_BENCH_LANG", "en")
SCREEN = os.environ.get("QUNXIA_SCREEN_FILE", "/tmp/screen.png")
MIN_HOLD, MAX_HOLD, MAX_KEYS = 5, 1200, 100


def call(method, path, payload=None, timeout=240):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return {"ok": False, "error": f"cannot reach the game at {API}: {e}"}


def show(res):
    if res.get("ended"):
        keys = ("reason", "why", "message", "actions", "played_seconds")
        print("BENCHMARK ENDED | " + json.dumps({k: res.get(k) for k in keys}, ensure_ascii=False))
        return 3
    if res.get("ok", True) is False:
        print("ERROR | " + str(res.get("error") or "the game API rejected the action"))
        return 1
    bits = []
    if res.get("width") is not None and res.get("height") is not None:
        bits.append(f'{res["width"]}x{res["height"]}')
    img = res.get("image")
    if img:
        with open(SCREEN, "wb") as f:
            f.write(base64.b64decode(img.split(",", 1)[1]))
        bits.append(f"screen saved to {SCREEN}; view it")
    print(" | ".join(bits) or "ok")
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="cli.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("guide")
    sub.add_parser("look")
    pr = sub.add_parser("press")
    pr.add_argument("keys", nargs="+")
    pr.add_argument("--hold", type=int, default=None)
    a = p.parse_args(argv)
    if a.cmd == "guide":
        url = os.environ.get("QUNXIA_BENCH_HELP_URL") or f"{API}/help?{urllib.parse.urlencode({'lang': LANG})}"
        with urllib.request.urlopen(url, timeout=30) as r:
            print(adapt_guide(r.read().decode("utf-8"), benchmark=True))
        return 0
    if a.cmd == "look":
        return show(call("GET", "/screen"))
    if not 1 <= len(a.keys) <= MAX_KEYS:
        print(f"ERROR | press takes 1 to {MAX_KEYS} keys"); return 1
    if a.hold is not None and not MIN_HOLD <= a.hold <= MAX_HOLD:
        print(f"ERROR | --hold must be {MIN_HOLD} to {MAX_HOLD}"); return 1
    payload = {"key": a.keys if len(a.keys) > 1 else a.keys[0]}
    if a.hold is not None:
        payload["hold"] = a.hold
    res = call("POST", "/key?scale=1&image=0", payload)
    code = show(res)
    if code == 0:
        # Benchmark mode returns metadata only; look, as the MCP tool tells the model to.
        return show(call("GET", "/screen"))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''
