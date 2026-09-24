"""Read the events the game keeps no persistent record of out of the published replays.

    python3 figures/replay_scan.py [VIDEO_DIR]

Five panels the game draws at a fixed screen position are matched against
every frame of every published replay video, by normalised cross-correlation
against the crops in templates/ (cut from frames of this field and described
in templates.json). A panel counts when it scores above the threshold over
HOLD seconds of play: two consecutive frames of a replay at 8 times speed and
20 frames a second, one frame at 24 times speed, where a frame spans 1.2
seconds of play. The game holds these panels for a second or more, while a
single frame of an 8-times replay above the threshold is a transition fluke
(two were found, at 0.90 and 0.91, on inn scenes without a prompt). Scores are
kept per video second as the best minimum over the frames of one hold; the maximum of a session with no hit is
reported beside it so the margin is on record. The five events:

    hermit    the hermit's portrait in the dialogue frame: the conversation began
    compass   the coordinate line the compass adds to the item screen: the compass is held
    battle    the acting character's card in a fight: a fight was entered
    defeat    the banner the game draws when the party loses: the fight ran to a verdict
    prompt    the yes-or-no prompt of a recruitable character; the game holds it
              until a key is pressed, so the companion joined when the first key
              pressed after it appeared is `y`

A sixth event, the message the game draws when an item enters the bag, is
centred on the screen and as wide as the name of the item, so its first two
glyphs, 得到 (obtained), are searched along their row over the offsets the
names produce. It confirms a change of the bag, which the model need not have
looked at, so a single frame counts; its template never scored above 0.35
without the message.

    obtained  an item entered the bag

A seventh reading is the scene the party is in. On entering a scene from the
world map the game draws the scene's name in a banner at the top of the
screen: a rounded cream border around a dark box with the name in gold, centred
and as wide as the name. Every frame is tested for that box; a rising edge is
an entry, and the interior of the box is matched against the banners in
templates/scenes/, one file per scene name, so the count of distinct scenes and
the visits to the home (王居) are read from the replay.

The scan also finds the first fully black game frame of each replay at the
full frame rate of the video: the game blacks the screen on a scene change,
and the first one in a session that starts inside the compound is the exit
onto the world map. The number of actions before it is the crossing count,
and it agrees with the count the service recorded from the same signal on
every session that carries both.

Videos are read from VIDEO_DIR/<id>.mp4, or fetched from the video_url of
each session on record when the directory has none. The output,
replay_events.json, is committed beside the snapshot; field.py reads it.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import field  # noqa: E402

META = json.load(open(os.path.join(HERE, "templates", "templates.json"), encoding="utf-8"))
W, H = META["frame"]
THRESH = META["threshold"]
NAMES = ("hermit", "compass", "battle", "defeat", "prompt")
SCENES_DIR = os.path.join(HERE, "templates", "scenes")
HOME = "王居"                       # the banner of the home scene
BANNER_TOP, BANNER_H, BANNER_W = (7, 17), (20, 27), (24, 150)   # rows of the top border, box height, box width
WHITE = 235
TPL = {n: np.asarray(Image.open(os.path.join(HERE, "templates", n + ".png")).convert("L"), dtype=np.float32)
       for n in NAMES + ("obtained",)}
HOLD = 0.8        # seconds of play a panel must stay above the threshold
CANDIDATE = 0.6   # scores above this are kept per second, so the threshold can be revisited without a rescan


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0





def _runs(row):
    """(start, length) of the longest run of True in a boolean row."""
    if not row.any():
        return 0, 0
    d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k] - starts[k])


def scene_banner(f):
    """The interior of the scene-name banner in a gray frame, or None.

    The banner's border is a cream rounded rectangle whose top edge sits in a
    fixed band of rows and whose width follows the name; the box is centred on
    the screen. The top and bottom edges must both be present and agree in
    extent, which no dialogue box, prompt or menu of the game satisfies."""
    band = f[BANNER_TOP[0]:BANNER_TOP[1], 40:280] > WHITE
    for i in range(band.shape[0]):
        x0, w = _runs(band[i])
        if not BANNER_W[0] <= w <= BANNER_W[1]:
            continue
        x0 += 40
        cx = x0 + w / 2
        if not 140 <= cx <= 180:
            continue
        top = BANNER_TOP[0] + i
        for h in range(BANNER_H[0], BANNER_H[1]):
            y = top + h
            if y >= f.shape[0]:
                break
            # the bottom edge runs between rounded corners, so it is a few
            # pixels shorter than the top edge and starts a little to the right
            bx0, bw = _runs(f[y, 40:280] > WHITE)
            if -3 <= bx0 + 40 - x0 <= 5 and 0.8 * w <= bw <= w / 0.8:
                return f[top + 3:y - 2, x0 + 3:x0 + w - 3], (x0, top, x0 + w, y)
    return None


def load_scene_templates():
    out = []
    for name in sorted(os.listdir(SCENES_DIR)) if os.path.isdir(SCENES_DIR) else []:
        if name.endswith(".png"):
            # 'X.png' and its variants 'X.2.png' all name the scene X
            out.append([name[:-4].split(".")[0], np.asarray(Image.open(os.path.join(SCENES_DIR, name)).convert("L"), dtype=np.float32)])
    return out


def same_banner(a, b):
    """Whether two banner interiors show the same name: the same width within
    two pixels and a normalised cross-correlation above 0.85 at the best of
    the small offsets a one-pixel difference in the detected box produces."""
    if abs(a.shape[1] - b.shape[1]) > 2 or abs(a.shape[0] - b.shape[0]) > 2:
        return False
    h, w = min(a.shape[0], b.shape[0]) - 2, min(a.shape[1], b.shape[1]) - 2
    best = 0.0
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            for p, q in ((a[dy:dy + h, dx:dx + w], b[:h, :w]), (a[:h, :w], b[dy:dy + h, dx:dx + w])):
                if p.shape == q.shape == (h, w):
                    best = max(best, ncc(p, q))
    return best > 0.85



def banner_name(crop, known):
    """The scene name the crop matches, or a new placeholder name saved to
    templates/scenes/ so it can be named by hand."""
    for name, tpl in known:
        if same_banner(crop, tpl):
            return name
    os.makedirs(SCENES_DIR, exist_ok=True)
    name = "scene-%02d" % (len(os.listdir(SCENES_DIR)) + 1)
    Image.fromarray(crop.astype(np.uint8)).save(os.path.join(SCENES_DIR, name + ".png"))
    known.append([name, crop.copy()])
    return name


def video_fps(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                          "stream=r_frame_rate", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    a, b = out.strip().split("/") if "/" in out else (out.strip(), "1")
    return float(a) / float(b)


def second_scores(path, known, speed):
    """Best normalised cross-correlation per video second for every panel, over
    every frame of the video: the five fixed panels in their boxes and the 得到
    glyphs slid along the row the game centres its obtained-item message on."""
    x0, y0, x1, y1 = META["obtained"]["box"]
    lo, hi = META["obtained"]["slide"]
    t = TPL["obtained"] - TPL["obtained"].mean()
    tn = np.sqrt((t * t).sum())
    h, w = t.shape
    fps = video_fps(path)
    proc = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-vf",
                             f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                            stdout=subprocess.PIPE)
    best = {n: [] for n in NAMES + ("obtained",)}
    need = max(1, int(np.ceil(HOLD * fps / speed - 1e-9)))   # frames that span HOLD seconds of play
    recent = {n: [] for n in NAMES}         # the scores of the last `need` frames per panel
    entries = []                             # (second, scene name) at each banner's rising edge
    pending = None                           # a banner just risen: settle a few frames before matching
    showing = False
    i = 0
    while True:
        buf = proc.stdout.read(W * H)
        if len(buf) < W * H:
            break
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.float32)
        s = int(i / fps)
        for n in best:
            if s >= len(best[n]):
                best[n].extend([0.0] * (s + 1 - len(best[n])))
        for n in NAMES:
            bx0, by0, bx1, by1 = META[n]["box"]
            score = ncc(f[by0:by1, bx0:bx1], TPL[n])
            recent[n] = (recent[n] + [score])[-need:]
            if len(recent[n]) == need:
                best[n][s] = max(best[n][s], min(recent[n]))
        band = f[y0:y1]
        win = np.lib.stride_tricks.sliding_window_view(band, (h, w))[0, lo:hi + 1]
        wm = win - win.mean(axis=(1, 2), keepdims=True)
        den = np.sqrt((wm * wm).sum(axis=(1, 2))) * tn
        sc = (wm * t).sum(axis=(1, 2)) / np.where(den > 0, den, np.inf)
        best["obtained"][s] = max(best["obtained"][s], float(sc.max()))
        b = scene_banner(f)
        if b is not None and not showing:
            pending = [s, b[0], 6]
        elif b is not None and pending is not None:
            pending[1] = b[0]
            pending[2] -= 1
            if pending[2] == 0:
                entries.append((pending[0], banner_name(pending[1], known)))
                pending = None
        elif b is None and pending is not None:
            entries.append((pending[0], banner_name(pending[1], known)))
            pending = None
        showing = b is not None
        i += 1
    proc.stdout.close()
    proc.wait()
    if pending is not None:
        entries.append((pending[0], banner_name(pending[1], known)))
    return best, entries


def panel(sec, speed):
    idx = [s for s, v in enumerate(sec) if v > THRESH]
    return {"seconds": len(idx), "max": round(max(sec), 3) if sec else None,
            "first_minute": round(idx[0] * speed / 60, 1) if idx else None,
            "minutes": [round(s * speed / 60, 1) for s in idx],
            "candidates": [[s, round(v, 3)] for s, v in enumerate(sec) if v > CANDIDATE]}


def first_black(path):
    """Video second of the first fully black game frame, or None."""
    err = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", path, "-vf",
                          f"crop={W}:200:0:0,blackdetect=d=0.03:pix_th=0.10", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(m.group(1)) for m in re.finditer(r"black_start:([0-9.]+)", err)]
    return starts[0] if starts else None


def scan(path, timeline, known):
    speed = timeline["speed"] if timeline else 8.0
    sec, entries = second_scores(path, known, speed)
    out = {"video_seconds": len(sec["obtained"])}
    away = [name for _, name in entries if name != HOME]
    out["scenes"] = {"entries": [{"minute": round(t * speed / 60, 1), "name": name} for t, name in entries],
                     "distinct": len(set(away)),
                     "first_minute": round(min((t for t, n in entries if n != HOME), default=0) * speed / 60, 1) if away else None}
    hits = {}
    for n in NAMES + ("obtained",):
        out[n] = panel(sec[n], speed)
        hits[n] = [s for s, v in enumerate(sec[n]) if v > THRESH]
    black = first_black(path)
    out["first_black_second"] = black
    out["crossing_actions"] = (sum(1 for m in timeline["marks"] if m["t"] <= black)
                               if black is not None and timeline else None)
    out["recruited_minute"] = recruited(hits["prompt"], timeline, speed)
    return out


def recruited(prompt_seconds, timeline, speed):
    """Minute of the yes that answered the join prompt, or None. The game holds
    the prompt until a key is pressed, so the answer is the first key pressed
    after the prompt appeared; any other key dismisses it."""
    if not prompt_seconds or not timeline:
        return None
    marks = sorted(timeline["marks"], key=lambda m: m["t"])
    for i in prompt_seconds:
        after = [m for m in marks if m["t"] >= i]
        if after and after[0]["keys"] and after[0]["keys"][0][0] == "y":
            return round(after[0]["t"] * speed / 60, 1)
    return None


def main():
    vdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "videos")
    os.makedirs(vdir, exist_ok=True)
    rows = field.load_runs(dedup=False, keep_excluded=True)   # the scan covers the whole catalogue
    known = load_scene_templates()
    events = {}
    for r in sorted(rows, key=lambda r: (r["agent"], r["id"])):
        path = os.path.join(vdir, r["id"] + ".mp4")
        if not os.path.exists(path):
            url = r.get("video_url")
            if not url:
                sys.exit(f"{r['agent']} {r['id']}: no video on record")
            urllib.request.urlretrieve(url, path)
        tl_path = os.path.join(HERE, "timelines", r["id"] + ".json")
        tl = json.load(open(tl_path, encoding="utf-8")) if os.path.exists(tl_path) else None
        events[r["id"]] = {"agent": r["agent"], **scan(path, tl, known)}
        e = events[r["id"]]
        print(f"{r['agent']:22s} {r['id']} " + " ".join(
            f"{n}={e[n]['first_minute']}" for n in NAMES + ("obtained",)) + f" recruited={e['recruited_minute']} scenes={[x['name'] for x in e['scenes']['entries']]}",
            file=sys.stderr, flush=True)
    json.dump(events, open(os.path.join(HERE, "replay_events.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
