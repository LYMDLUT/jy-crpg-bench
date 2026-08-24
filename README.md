# QunXia

Native macOS runner for the original DOS 金庸群俠傳 (`Z.COM` / DOS4GW), plus an
HTTP and MCP interface so an LLM agent can play it. The game binary is untouched:
DOSBox Pure emulates the PC, Metal presents the VGA framebuffer, CoreAudio plays
the Sound Blaster output.

## Setup

```sh
# original game files (not in this repo)
mkdir -p game && cp -R /path/to/jinyong/* game/

./Scripts/run.sh
```

The prebuilt core is in `Cores/`. To rebuild it:

```sh
git clone https://github.com/schellingb/dosbox-pure.git vendor/dosbox-pure
make -C vendor/dosbox-pure -j
cp vendor/dosbox-pure/dosbox_pure_libretro.dylib Cores/
```

Window keys: arrows, enter, space, esc, y/n and the 注音 name entry all work.
⌘1-⌘5 scale, ⌘I hides the log pane, ⌘0 4:3, ⌘S/⌘L quick save-load, ⌘M mute,
⌃⌘F fullscreen. The window snaps to whole multiples of 320×200, so the game is
never letterboxed.

## Agent API (http://127.0.0.1:8765)

Every call that changes game state runs the action, waits for the screen to
react and then to hold still, and returns the resulting screenshot. One request
is one action and one observation.

```
GET  /state                        screen + geometry + "screen" hash
GET  /frame.png?scale=2            raw PNG
GET  /history  /keys  /slots  /help
POST /key    {"key":"down"}        "hold" frames, default 4
POST /keys   {"keys":["up","ok"]}  "gap" frames between, default 6
POST /text   {"text":"j;6"}        type a string
POST /wait   {"ms":1000}
POST /mouse  {"dx":10,"dy":0,"click":"left"}
POST /save   {"slot":1} | {"name":"before-boss"}
POST /load   {"slot":1}
POST /reset
```

`image` comes back as a base64 PNG data URI. `?format=png` for raw bytes,
`?image=0` to skip it, `?scale=1..6` for size, `?react` `?stable` `?maxsettle`
to tune the wait, `?settle=N` for a fixed wait. `"changed": false` means the
action had no visible effect. `frame` counts distinct video frames and stalls on
a static screen; `ticks` always rises while the emulator runs.

Boot takes about 14s. Poll `/state` and watch the `screen` hash to know when it
has finished.

## MCP

`mcp-server/` exposes the same thing over MCP, with the controls, the 注音
layout, the objectives and the cutscene gotcha written into the server
instructions and tool descriptions, so a fresh agent knows how to play.

```json
{
  "mcpServers": {
    "qunxia": {
      "command": "uv",
      "args": ["run", "--with", "mcp", "/ABSOLUTE/PATH/jy-metal/mcp-server/server.py"]
    }
  }
}
```

Tools: `look` `guide` `press` `press_sequence` `move` `interact` `open_menu`
`type_text` `wait` `save_state` `load_state` `list_states` `reset_game`. Every
action tool returns the resulting screen as an image. `QUNXIA_API` and
`QUNXIA_SCALE` override the endpoint and screenshot size.

`Scripts/play.py` is the equivalent shell client.

## Notes on playing it

- While a scripted event is running the game ignores movement and menu keys, and
  any key only advances the dialogue. `esc` opening the 醫療/解毒/物品/狀態 menu
  is the reliable test for whether you are free to act.
- Enter and space are equivalent in the world: confirm, advance dialogue,
  interact with what you face. One arrow press turns and steps one tile.
- Names are entered with the game's 注音 IME in the 大千 layout: type the zhuyin
  keys, then the digit for the candidate. `j;6` then `1` gives 王.

## Performance

x86 is JIT-compiled to ARM64 (DOSBox Pure dynrec, `C_TARGETCPU ARMV8LE`). M3
Ultra, 10s at the title screen, audio on:

| `dosbox_pure_cycles` | CPU (1 core) | emulated fps | boot to title |
|---|---:|---:|---:|
| `max` | 99.5% | 70.22 | 15.8s |
| `auto` | 81.3% | 70.19 | 19.5s |
| **fixed 77000** | **31.3%** | **70.17** | **15.9s** |
| fixed 26800 | 15.6% | 70.04 | |

The game targets a 486/Pentium, so anything above a Pentium-100 budget goes to
its own idle spin loops. Fixed 77000 is the default. Override with
`QUNXIA_SET="dosbox_pure_cycles=max"` or `--set dosbox_pure_cycles=200000`.

## Layout

```
Sources/CoreHost/    libretro host: dlopen, env callbacks, video/audio/input
Sources/QunXia/      Emulator (emulation thread + action queue), MetalView,
                     AudioOut, ControlAPI, HistoryView
mcp-server/          MCP wrapper plus the game knowledge an agent needs
Cores/               dosbox_pure_libretro.dylib
game/                original game files
saves/               emulator snapshots
```

DOSBox Pure is GPLv2, from `schellingb/dosbox-pure` @ `7f6e8fb`.
