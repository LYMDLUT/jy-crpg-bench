"""Say whether a capture is the 1996 binary, and if so where its clock starts.

    python3 gate.py <video> [t0] [t1]

The original game draws its opening room from fixed tiles, so the opening room of a
benchmark replay matches a capture of it above 0.90 once the crop is fitted. A remake
redraws the same room - cleaner fonts, retouched art, another hero sprite - and no scale
of the fit reaches that score, which is how the two complete runs dropped from the human
rows were recognised. Above the line the capture goes through the anchor: the frame on
which the hero stands on his spawn tile facing the soft-star, the first black frame a
second after it, and the keypresses between. Below it the capture is dropped and its
score is the reason, recorded in dropped.json so the rejections are auditable too.
"""
import json
import os
import subprocess
import sys

import read_video as RV
import respawn as R

OG = 0.90
HERE = os.path.dirname(os.path.abspath(__file__))
DROPPED = os.path.join(HERE, "dropped.json")


def fit(video, t0, t1):
    """crop the capture, or None when the opening room never appears."""
    out = subprocess.run(["python3", "read_video.py", "findcrop", video, str(t1 - t0), "1", str(OG)],
                         capture_output=True, text=True, cwd=HERE).stdout
    for l in out.splitlines():
        if "crop=" in l:
            return l.split("crop=")[1].split()[0], float(l.split("ncc")[1].split()[0]), l
    return None, None, out.strip().splitlines()[-1] if out.strip() else "no output"


def main(video, t0=0.0, t1=600.0):
    t0, t1 = float(t0), float(t1)
    name = os.path.basename(video).split(".")[0]
    crop, ncc, line = fit(video, t0, t1)
    print(f"{name}: {line}")
    if crop is None or ncc < OG:
        d = json.load(open(DROPPED)) if os.path.exists(DROPPED) else {}
        d[name] = {"video": video, "room_ncc": ncc, "og": 0.90,
                   "reason": "the opening room of the 1996 binary does not reach 0.90 at any scale"}
        json.dump(d, open(DROPPED, "w"), ensure_ascii=False, indent=1)
        print(f"{name}: DROPPED, room {ncc}, gate {OG} (recorded in dropped.json)")
        return None
    rec = {"id": name, "video": video, "class": "unclassified", "crop": crop, "start_s": 0.0,
           "crossing_s": min(t1, 90.0), "duration_s": t1}
    print(f"{name}: original game (room {ncc} >= {OG}), cropping {crop} and anchoring")
    return R.run(rec, t0, min(t1, 90.0))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], *(a[1:3] if len(a) > 2 else (a[1:] if len(a) > 1 else ())))
