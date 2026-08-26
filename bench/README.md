# Benchmark harness

One game per model, twenty minutes, recorded end to end and published.

```
POST /session {"agent":"your-model"}   ->  base_url, seconds, ends_at
     play at  <base_url>/api/...       (the game API, unchanged)
     when the clock runs out every call answers 410 with
     {"ended": true, "video_url": ..., "catalog_url": ...}
GET  /catalog                          ->  every run, with its video
```

Live: <https://jy-crpg-bench-366646433082.us-central1.run.app>

## What a run looks like

1. An agent asks for a session and gets its own URL prefix. The game behind it
   is a separate process with its own emulator, so runs cannot see each other.
2. The session starts in the opening room with a character already made.
   Creating one means driving the 注音 IME, which measures knowledge of input
   methods rather than play, and it is where runs used to end.
3. The agent plays for twenty minutes. `<base_url>/api/help` is the whole
   briefing, the same text the shared instance serves.
4. The clock runs out. The session is finalised whether or not anyone is
   watching: the recording is rendered to MP4, uploaded, and listed. The next
   call the agent makes returns 410 and tells it to stop, with the video link.

Nothing has to be started or stopped by hand. Point an agent at `/session` and
collect the video afterwards.

## Recording

A recording is the tile deltas the browser stream already produces, kept with
timestamps together with the keys that caused them and who sent them. Rendering
replays them onto a canvas and pipes raw frames to ffmpeg, so it needs no
browser. The video carries the model name and the keys held at each moment.

Two things that were wrong earlier and are fixed here: video no longer opens on
black, because rendering starts at the first frame rather than at time zero;
and the game switching between 320x200 and 640x400 mid run no longer breaks it,
because frames are scaled into a fixed area rather than sized from the first
frame.

## Layout

```
broker.py      sessions, time limits, finalising, catalogue, proxy
bootstrap.py   plays the opening once to create the state runs start from
render.py      recording -> MP4
catalog.html   the page
Dockerfile     game, core, renderer and broker in one image
```

## Running it locally

```sh
./server/build.sh                       # libqunxia for this platform
python3 -m venv .venv && .venv/bin/pip install aiohttp pillow numpy
QUNXIA_RUN_SECONDS=120 QUNXIA_PYTHON=$PWD/.venv/bin/python \
  QUNXIA_CORE=$PWD/Cores/dosbox_pure_libretro.dylib \
  PYTHONPATH=$PWD/bench .venv/bin/python bench/broker.py
```

The start state is built on first boot if it is missing. A DOSBox Pure
savestate belongs to the core build that wrote it, so it cannot ship with the
image and is made wherever the service runs.

## Deploying

```sh
gcloud builds submit --config cloudbuild.yaml --substitutions=_TAG=vN .
gcloud run deploy jy-crpg-bench --region us-central1 \
  --image .../jy-crpg-bench:vN --allow-unauthenticated \
  --cpu 4 --memory 4Gi --no-cpu-throttling \
  --min-instances 1 --max-instances 1 --concurrency 80 --timeout 3600 \
  --set-env-vars QUNXIA_GCS_BUCKET=jy-crpg-bench-runs,QUNXIA_RUN_SECONDS=1200
```

`--max-instances 1` is deliberate. A session is an emulator process living in
one instance memory, and Cloud Run cannot route a later request to the instance
that holds it, so spreading sessions across instances would break them. One
always-on instance with four vCPU carries four concurrent runs, since a session
costs about 15 percent of a core. Going wider means routing by session id in
front of several services rather than raising this number.

Videos and the catalogue live in the bucket, because container storage does not
survive a restart.

| variable | default | |
|---|---|---|
| `QUNXIA_RUN_SECONDS` | 1200 | length of a run |
| `QUNXIA_MAX_SESSIONS` | 4 | concurrent runs |
| `QUNXIA_GCS_BUCKET` | | publish videos here, else served from the service |
| `QUNXIA_PUBLIC_BASE` | | absolute URLs in replies |
