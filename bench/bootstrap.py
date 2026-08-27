#!/usr/bin/env python3
"""Create the state every benchmark run starts from.

A DOSBox Pure savestate belongs to the core build that wrote it, so the state
cannot be shipped between platforms and has to be made wherever it will be
used. This plays the opening once: new game, a name through the 注音 IME,
accept the roll, then read the wake-up scene to its end, and saves the moment
the player is free to move with the 軟體娃娃 still unspoken to.
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

from PIL import Image


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


def in_game(g):
    """Positive proof this is the world view and not a boot or title screen.

    "Pressing a key changed the screen" is not proof: a BBS crack screen
    animates on its own and passes that test. What separates them is that the
    game fills the frame. Measured: the boot screen is 27% lit, the world view
    97%.
    """
    im = Image.open(io.BytesIO(g.png()))
    px = im.convert("RGB").getdata()
    lit = sum(1 for r, gg, b in px if max(r, gg, b) > 40) / (im.width * im.height)
    return lit > 0.75


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

    # Bounded by the clock, not by a round count. A round is only slow when
    # there is still dialogue to clear, so on a slower machine the old budget
    # of 30 rounds ran out while the opening scene was still playing, and
    # every run on that host then began at the boot screen.
    log("reading the opening scene to its end")
    deadline = time.time() + float(os.environ.get("QUNXIA_OPENING_SECONDS", "420"))
    rounds = 0
    while True:
        rounds += 1
        for _ in range(4):
            g.key("enter")
        if free_to_act(g):
            log(f"  free to move after {rounds} rounds")
            break
        if time.time() > deadline:
            raise RuntimeError(f"never became free to move after {rounds} rounds")

    if has_dialogue(g.png()):                 # last check before committing
        raise RuntimeError("dialogue reappeared before the snapshot")
    if not in_game(g):
        raise RuntimeError("the screen is too dark to be the world view; this "
                           "is a boot or title screen and must not be saved")
    out = g.call("POST", f"/api/snapshot?token={token}")
    if not out.get("ok"):
        raise RuntimeError(f"snapshot failed: {out}")
    log(f"start state written: {out['path']} ({out['bytes']} bytes)")
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
