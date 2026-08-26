#!/usr/bin/env python3
"""Create the state every benchmark run starts from.

A DOSBox Pure savestate belongs to the core build that wrote it, so the state
cannot be shipped between platforms and has to be made wherever it will be
used. This plays the opening once: new game, a name through the 注音 IME,
accept the roll, then read the wake-up scene to its end, and saves the moment
the player is free to move with the 軟體娃娃 still unspoken to.
"""
import json
import sys
import time
import urllib.error
import urllib.request


class Game:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, body=None, timeout=180):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={"Content-Type": "application/json",
                                    "X-Agent": "bootstrap"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def key(self, k, **kw):
        return self.call("POST", "/api/key", {"key": k, **kw})

    def keys(self, ks):
        return self.call("POST", "/api/keys", {"keys": ks})

    def wait(self, ms):
        return self.call("POST", "/api/wait", {"ms": ms})

    def screen_hash(self):
        return self.call("GET", "/api/screen?image=0").get("frame")

    def png(self):
        import base64
        d = self.call("GET", "/api/screen")
        return base64.b64decode(d["image"].split(",", 1)[1])


def sha(b):
    import hashlib
    return hashlib.sha1(b).hexdigest()


def has_dialogue(png):
    """A dialogue box is a bright white frame across the lower half of a screen
    that is otherwise browns and yellows, so near-white pixels down there are a
    reliable tell. Measured: about 7 percent with a box, under 1 without."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    crop = im.crop((0, int(h * 0.55), w, h))
    white = sum(1 for r, g, b in crop.getdata() if min(r, g, b) > 200)
    return white > crop.width * crop.height * 0.01


def quiet(g, samples=3):
    """No dialogue across a short window. A single sample can land in the gap
    between two lines and read as clear while the scene is still running."""
    for _ in range(samples):
        if has_dialogue(g.png()):
            return False
        g.wait(700)
    return not has_dialogue(g.png())


def free_to_act(g):
    """Nothing scripted running: no dialogue for a while, and esc opens and
    closes the menu leaving the screen exactly as it was."""
    if not quiet(g):
        return False
    before = sha(g.png())
    g.key("esc")
    if sha(g.png()) == before:
        return False
    g.key("esc")
    return sha(g.png()) == before


def build(base, token, log=print):
    g = Game(base, token)
    log("waiting for the title screen")
    g.wait(16000)
    for _ in range(6):
        before = sha(g.png())
        g.key("enter")
        if sha(g.png()) != before:
            break
        g.wait(3000)

    log("naming the character through the 注音 IME")
    g.keys(["j", ";", "6"])        # ㄨㄤˊ
    g.keys(["1", "enter"])         # pick 王, confirm
    g.key("y")                     # accept the rolled attributes
    g.wait(9000)

    log("reading the opening scene to its end")
    for attempt in range(30):
        for _ in range(4):
            g.key("enter")
        if free_to_act(g):
            log(f"  free to move after {attempt + 1} rounds")
            break
    else:
        raise RuntimeError("never became free to move")

    if has_dialogue(g.png()):                 # last check before committing
        raise RuntimeError("dialogue reappeared before the snapshot")
    out = g.call("POST", f"/api/snapshot?token={token}")
    if not out.get("ok"):
        raise RuntimeError(f"snapshot failed: {out}")
    log(f"start state written: {out['path']} ({out['bytes']} bytes)")
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
