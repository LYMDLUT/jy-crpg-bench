#!/usr/bin/env python3
"""Tiny client for the QunXia control API.

  ./Scripts/play.py state
  ./Scripts/play.py key down
  ./Scripts/play.py keys up ok
  ./Scripts/play.py text "j;6"
  ./Scripts/play.py wait 2000
  ./Scripts/play.py save inn      /  load inn
  ./Scripts/play.py shot out.png

Every command writes the resulting screen to /tmp/qunxia.png unless a path is given.
"""
import base64, json, os, subprocess, sys, urllib.request

API = os.environ.get("QUNXIA_API", "http://127.0.0.1:8765")
OUT = "/tmp/qunxia.png"


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def save_shot(res, path=OUT):
    img = res.pop("image", None)
    if img:
        open(path, "wb").write(base64.b64decode(img.split(",", 1)[1]))
        res["saved"] = path
    return res


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "state":
        res = call("GET", "/state")
    elif cmd == "help":
        with urllib.request.urlopen(API + "/help") as r:
            print(r.read().decode())
            return 0
    elif cmd == "key":
        res = call("POST", "/key", {"key": args[0]})
    elif cmd == "keys":
        res = call("POST", "/keys", {"keys": args})
    elif cmd == "text":
        res = call("POST", "/text", {"text": args[0]})
    elif cmd == "wait":
        res = call("POST", "/wait", {"ms": int(args[0]) if args else 1000})
    elif cmd in ("save", "load"):
        key = "name" if args and not args[0].isdigit() else "slot"
        val = args[0] if args else 1
        res = call("POST", "/" + cmd, {key: int(val) if key == "slot" else val})
    elif cmd == "reset":
        res = call("POST", "/reset")
    elif cmd == "shot":
        res = call("GET", "/state")
    else:
        print(__doc__.strip())
        return 1

    path = args[0] if cmd == "shot" and args else OUT
    print(json.dumps(save_shot(res, path), ensure_ascii=False))
    if sys.stdout.isatty() and os.path.exists(path):
        subprocess.run(["open", path], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
