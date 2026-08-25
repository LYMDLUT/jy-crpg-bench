# Headless server

Runs the game with no display and streams the VGA framebuffer to a browser.

- `tiles.c` diffs the framebuffer against the last frame sent and emits only the
  16x10 tiles that changed. `CoreHost.c` is reused unmodified: it is portable C.
- `server.py` loads both through ctypes, paces the emulation on its own thread,
  deflates each delta and fans it out over one WebSocket that also carries input.
- `index.html` reassembles the tiles onto a canvas with `DecompressionStream`.

## Deploy

```sh
./build.sh                      # -> libqunxia.so (Linux)
python3 -m venv .venv && .venv/bin/pip install aiohttp
.venv/bin/python server.py      # PORT=8080
```

Needs `../cores/dosbox_pure_libretro.so` (libretro buildbot) and `../game/`.

## Endpoints

- `/` browser client, WebSocket tile stream at `/ws`
- `/api/help` the whole game briefing as flat text, with this host's URLs baked
  in. The page shows it in a copy box so a user can paste it into their own
  LLM's system prompt and play without any harness of ours.
- `/api/state`, `/api/frame.png`, `/api/key`, `/api/keys`, `/api/text`,
  `/api/wait` mirror the native runner: apply input, wait for the screen to
  react and then settle, return the resulting PNG.

PNGs are written by a ~10 line encoder over `zlib` rather than pulling in an
image library.

## Why 26800 cycles

Measured on the target VM: at 77000 cycles the core runs 1.75x faster than the
70.09 fps it needs, which a shared-core instance cannot hold once burst credits
run out. At 26800 (486DX2-66, period-correct for a 1996 game) it runs 6.7x
faster than needed, about 15% of a core, and an e2-micro holds a full 70.1 fps
indefinitely. Override with `QUNXIA_CYCLES`.
