# Paper

ICLR 2027 submission draft for jy-crpg-bench.

- `src/` - LaTeX source (official ICLR 2027 style), `main.pdf` is the build
- `src/figures/make.py` - regenerates the data figures from the published catalogue numbers
- `src/figures/env.tex`, `keymap.tex` - TikZ sources of the environment and
  action-space figures; compile each with `pdflatex` in `src/figures/` to refresh its PDF
- `src/figures/architecture.svg` - the source of Figure 2, edited in Inkscape, with the
  three screenshots embedded and the lettering as paths. Export it from `paper/` with
  `inkscape src/figures/architecture.svg --export-area-page --export-type=pdf --export-filename=src/figures/architecture.pdf`
  and commit the SVG, the PDF and the rebuilt `main.pdf` together. `architecture.tex` is
  the TikZ layout the SVG started from and is not compiled.
- every number is generated from committed inputs: `src/figures/catalog_snapshot.json`
  and `src/figures/start.state` (the savestate every session boots into),
  plus `src/figures/timelines/<id>.json`, the published keypress timeline of
  every session the paper reads, which the replay-pattern macros are read from.
  `src/figures/recover_sessions.py` rebuilds `recovered_sessions.json`, one row
  per session the live catalogue no longer lists, from the preserved saves in
  `src/figures/slots/` and the timelines; `catalog_backup_20260911T174413Z.json`
  is the catalogue as it stood before it was cleared for the final sweep.
  `field.py` merges the three, leaves out the models in its `EXCLUDED` list
  (a version with two later versions of its line in the field) and credits a
  model with every rung any of its sessions reached; `slots.py` decodes every preserved save in
  `src/figures/slots/`; `replay_scan.py` matches five fixed panels of the game
  (`src/figures/templates/`) and the message drawn when an item enters the
  bag against every frame of every published replay video, keeping the best
  score of each second, and writes `replay_events.json`, the record of the
  events the game keeps only on screen, the item reading for sessions whose bag no record
  carries, the scenes each session entered (read by name from the banner
  the game draws on entry, matched against `src/figures/templates/scenes/`,
  one file per scene name), and, from the first fully black frame, the
  actions each session took to reach the world map
  (run it with a directory of the videos, or let it fetch them).
  `figures/emit_numbers.py` writes `figures/numbers.tex`,
  `figures/make_metrics.py` writes `tables/family.tex` and `tables/runs.tex`,
  `figures/emit_books.py` writes `tables/books.tex` from the save decoder's
  book table, `figures/emit_effort.py` writes `tables/effort.tex` (sessions,
  actions, keys per action and the time between actions per model),
  `figures/emit_milestones.py` writes `tables/milestones.tex` (each
  milestone in actions and minutes from the replays and timelines), `figures/make.py` draws the data figures, and
  `check_consistency.py` fails if a claim drifts from the snapshot
- `src/figures/human_sessions.json` - the published videos of human players
  behind the two reference rows of Figure 3: for each, the class (speedrun or
  playthrough), the crop that maps the capture onto the native frame, the start
  of play, the minute of every milestone with the evidence it was read from, and
  the keypresses to the world map. The tools are in `src/figures/human/`:
  `gate.py` admits a capture when the opening room of a benchmark replay matches
  it at 0.90 or above and records every rejection in `dropped.json`;
  `read_video.py` locates the game frame (`findcrop`, `edgecrop`, `refinecrop`,
  with `cropfit.py` for the whole-pixel fit), crops and scales the capture,
  matches the panels and the messages, and counts tile steps and screen changes,
  which `actions.py` prints per capture; `respawn.py` sets the start of play on
  the first frame in which the hero stands on his spawn tile with his back to the
  camera, frame zero of a benchmark replay, and `spawnscan.py` does the same for
  one capture. The evidence sheets are under `human/evidence/<video id>/`, the
  videos themselves are not tracked, and `field.human_rows()` turns the file into
  the two rows. `src/figures/human/route.py` stitches the frames of a walk into
  the panels of the route figure (`src/figures/route-*.png`) from the same
  speedrun. `src/figures/model_route.py <session id>` draws the same compound
  panel from a benchmark replay, up to its first black frame, into
  `src/figures/route-model-<model>.png` with a `.txt` stamp naming the session;
  `emit_numbers.py` reads the stamp and refuses to run if the panel of a model
  was not drawn from the session the paper reports for it.
- `src/figures/first_hour.py` - writes the first 60 minutes of each four-hour session of a
  model with no hour session as an hour session (`<id>-h1`): a row in
  `catalog_snapshot_firsthour.json`, the timeline cut at minute 60 and the replay
  readings cut at minute 60. `field.load_runs()` adds these rows to the hour field.
- `src/figures/long_submissions.json` - every attempt at the four-hour budget with its
  status and reason. `long_cohort.py` selects the sessions that count (ended by the
  service at the budget, last key in the final two minutes) and refuses an attempt
  the manifest does not list;
  `field.long_attempts()` returns the archive and `field.load_long()` the sessions
  that count. `long-submissions.md` lists the decisions. Run
  `python3 -B figures/test_long_cohort.py` from `src/` after editing the manifest.
- `refs/` - the fourteen reference papers read while shaping the structure, by arXiv id
- `iclr2027/` - the official style-file kit as downloaded

Build, from a clean tree (no `.aux`/`.bbl`):

```sh
cd src
pdflatex -interaction=nonstopmode main.tex   # writes main.aux
bibtex main                                  # refs.bib -> main.bbl
pdflatex -interaction=nonstopmode main.tex   # pulls in the references
pdflatex -interaction=nonstopmode main.tex   # resolves citations and the TOC
```

Do not use `latexmk -pdf main.tex` on a clean tree: with no `main.aux` yet,
latexmk's scheduler sometimes orders `bibtex` before the first `pdflatex`;
bibtex then reads the stub `main.aux` that latexmk planted and the build
dies - a coin flip on every run.

Build with a scheme-full TeX Live. The Traditional Chinese terms are set with
`CJKutf8` in the `bsmi` face, which needs the `cjk` and `arphic` packages
(both in TeX Live full and on arXiv); the apt `cjk-latex` package omits the
C70 font-shape definitions and the build dies in an undefined macro two lines
after a font-substitution warning. A good build embeds only subset Type 1
fonts (`pdffonts main.pdf` shows every `bsmiu*` row as embedded) and its log
has no `Missing character` line. Two builds
of the same source differ only in the two timestamps hyperref stamps in and
pdftex's per-build /ID file identifier; commit the PDF alongside the source
change that produced it.

Before submission: comment out `\iclrfinalcopy` (double blind) and replace
the hanxiao.io URLs with an anonymised mirror.
