#!/usr/bin/env python3
"""Tiny client for the QunXia control API.

  ./Scripts/play.py screen
  ./Scripts/play.py key down
  ./Scripts/play.py keys up ok
  ./Scripts/play.py wait 2000
  ./Scripts/play.py save inn      /  load inn
  ./Scripts/play.py shot out.png

Every command writes the resulting screen to screen.png in QUNXIA_SCREEN_DIR,
or in a private per-user directory under the temp root, unless a path is
given. Concurrent clients of one user still share that file.
"""
import base64
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("QUNXIA_API", "http://127.0.0.1:8765").rstrip("/")
AGENT = os.environ.get("QUNXIA_AGENT", "play-cli")
SCREEN_DIR = os.environ.get("QUNXIA_SCREEN_DIR")


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "X-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except Exception:
            raise RuntimeError(f"game API returned HTTP {exc.code}") from exc


def screen_dir():
    """QUNXIA_SCREEN_DIR, or one directory per user under the temp root, so the
    path is the same from one command to the next and no other user's file is
    ever overwritten. A directory that is a symlink or belongs to another user
    is refused rather than written into."""
    directory = SCREEN_DIR or os.path.join(tempfile.gettempdir(), "qunxia-%d" % os.getuid())
    os.makedirs(directory, mode=0o700, exist_ok=True)
    st = os.lstat(directory)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError(f"{directory} is not a directory of this user")
    return directory


def save_shot(res, path=None):
    img = res.pop("image", None)
    if img:
        if path is None:
            path = os.path.join(screen_dir(), "screen.png")
        with open(path, "wb") as output:
            output.write(base64.b64decode(img.split(",", 1)[1]))
        res["saved"] = path
    return res


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd in ("screen", "state"):
        res = call("GET", "/screen")
    elif cmd == "help":
        with urllib.request.urlopen(API + "/help") as r:
            print(r.read().decode())
            return 0
    elif cmd == "key":
        if not args:
            raise ValueError("key requires a key name")
        res = call("POST", "/key?image=1", {"key": args[0]})
    elif cmd == "keys":
        if not args:
            raise ValueError("keys requires at least one key name")
        res = call("POST", "/key?image=1", {"key": args})
    elif cmd == "wait":
        import time
        time.sleep((int(args[0]) if args else 1000) / 1000.0)
        res = call("GET", "/screen")
    elif cmd in ("save", "load"):
        key = "name" if args and not args[0].isdigit() else "slot"
        val = args[0] if args else 1
        res = call("POST", f"/{cmd}?image=1", {key: int(val) if key == "slot" else val})
    elif cmd == "reset":
        url = "/reset"
        token = os.environ.get("QUNXIA_RESET_TOKEN")
        if token:
            url += "?token=" + urllib.parse.quote(token)
        res = call("POST", url)
    elif cmd == "shot":
        res = call("GET", "/screen")
    else:
        print(__doc__.strip())
        return 1

    if (cmd in ("key", "keys", "wait", "save", "load", "reset")
            and res.get("ok", True) and not res.get("image")):
        observed = call("GET", "/screen")
        if observed.get("image"):
            for field in ("image", "image_width", "image_height", "width",
                          "height", "frame"):
                if field in observed:
                    res[field] = observed[field]
            res["observation"] = "follow-up (not atomic on a shared session)"

    path = args[0] if cmd == "shot" and args else None
    result = save_shot(res, path)
    print(json.dumps(result, ensure_ascii=False))
    path = result.get("saved")
    if sys.stdout.isatty() and path and os.path.exists(path):
        opener = next((name for name in ("open", "xdg-open") if shutil.which(name)), None)
        if opener:
            subprocess.run([opener, path], check=False)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (IndexError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
