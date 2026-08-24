#!/usr/bin/env python3
"""MCP server exposing 金庸群俠傳 to any LLM agent.

Wraps the QunXia HTTP control API. Every action tool returns the resulting
screen as an image, so the agent sees what its input did.

Run:  uv run --with mcp mcp-server/server.py
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game_knowledge import GUIDE, INSTRUCTIONS

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent

API = os.environ.get("QUNXIA_API", "http://127.0.0.1:8765")
DEFAULT_SCALE = int(os.environ.get("QUNXIA_SCALE", "2"))

mcp = MCPServer("qunxia", instructions=INSTRUCTIONS)


class GameOffline(RuntimeError):
    pass


def _call(method, path, payload=None, timeout=240):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            raise GameOffline(f"{path} failed: HTTP {e.code}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise GameOffline(
            f"Cannot reach the game at {API} ({e}). Start it with "
            "'./Scripts/run.sh' in the repo, wait about 14 seconds for the "
            "title screen, then retry."
        )


def _result(res, note=""):
    """Turn an API response into MCP content: a short status line plus the screen."""
    out = []
    bits = []
    if not res.get("ok", True):
        bits.append("FAILED")
    if "changed" in res:
        bits.append("screen changed" if res["changed"] else
                    "screen did NOT change (the action had no visible effect)")
    if res.get("error"):
        bits.append(str(res["error"]))
    bits.append(f'{res.get("width")}x{res.get("height")}')
    line = (note + " | " if note else "") + " | ".join(str(b) for b in bits)
    out.append(TextContent(type="text", text=line))

    img = res.get("image")
    if img:
        out.append(ImageContent(
            type="image",
            data=img.split(",", 1)[1],
            mimeType="image/png",
        ))
    return out


def _act(path, payload, note="", **params):
    q = {"scale": DEFAULT_SCALE}
    q.update({k: v for k, v in params.items() if v is not None})
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return _result(_call("POST", f"{path}?{qs}", payload), note)


# ---------------------------------------------------------------- observation

@mcp.tool()
def look(scale: int = DEFAULT_SCALE) -> list:
    """Look at the current game screen without pressing anything.

    Use this to re-read a screen, or to check where you are after reconnecting.
    scale 1-6 enlarges the 320x200 image with nearest-neighbour (default 2);
    raise it if you are struggling to read small Chinese glyphs.
    """
    return _result(_call("GET", f"/state?scale={scale}"))


@mcp.tool()
def guide() -> str:
    """The full manual: controls, the 注音 name-entry layout, the story and
    objectives, and the cutscene gotcha. Read this before your first action."""
    return GUIDE


# -------------------------------------------------------------------- actions

@mcp.tool()
def press(key: str, times: int = 1, hold: int = 4, stable: int = None) -> list:
    """Press one key and return the screen it produced.

    key: up, down, left, right, enter (or ok), space, esc, y, n, a-z, 0-9,
         f1-f12, tab, backspace, or a combo like "alt+x".
    times: repeat the same key this many times (useful for walking or for
         advancing several dialogue lines).
    hold: frames to hold the key down, default 4. Raise it only if a press
         seems to be ignored.
    stable: frames the picture must hold still before the screenshot is taken.
         Raise it if you get a half-written dialogue line.

    Remember: during a cutscene every key just advances the dialogue.
    """
    if times > 1:
        return _act("/keys", {"keys": [key] * times, "hold": hold},
                    note=f"{key} x{times}", stable=stable)
    return _act("/key", {"key": key, "hold": hold}, note=key, stable=stable)


@mcp.tool()
def press_sequence(keys: list[str], gap: int = 6, stable: int = None) -> list:
    """Press several different keys in order, returning only the final screen.

    Use for a known menu path, e.g. ["esc", "down", "down", "enter"]. Prefer
    single presses when you are unsure what a screen will do, because you only
    see the result of the last key here.
    """
    return _act("/keys", {"keys": keys, "gap": gap},
                note=" ".join(keys), stable=stable)


@mcp.tool()
def move(direction: str, steps: int = 1) -> list:
    """Walk. direction is up, down, left, right.

    One step turns the character to face that way and moves one tile if it is
    not blocked, so walking into a person or object is how you talk to it. If
    nothing moves, you are either blocked or inside a cutscene.
    """
    if direction not in ("up", "down", "left", "right"):
        raise ValueError("direction must be up, down, left or right")
    return _act("/keys", {"keys": [direction] * max(1, steps), "gap": 6},
                note=f"move {direction} x{steps}")


@mcp.tool()
def interact() -> list:
    """Interact with whatever the character is facing, confirm a menu choice,
    or advance one line of dialogue. This sends enter."""
    return _act("/key", {"key": "enter"}, note="interact")


@mcp.tool()
def open_menu() -> list:
    """Open the in-game main menu (醫療 / 解毒 / 物品 / 狀態) by sending esc.

    Also the reliable test for whether a cutscene is still running: if the menu
    does not appear, you are not free to act yet.
    """
    return _act("/key", {"key": "esc"}, note="esc")


@mcp.tool()
def type_text(text: str) -> list:
    """Type a literal string, one key per character.

    For the character-name prompt the game runs a 注音 IME, so send the zhuyin
    keys rather than pinyin: "j;6" produces the candidate list for ㄨㄤˊ, then
    press the digit for the character you want. See guide() for the layout.
    """
    return _act("/text", {"text": text}, note=f"type {text!r}")


@mcp.tool()
def wait(ms: int = 1000) -> list:
    """Let the game run without pressing anything, then return the screen.

    Use it during boot, scene transitions, battle animations, and travel on the
    world map.
    """
    return _act("/wait", {"ms": ms}, note=f"wait {ms}ms")


# ----------------------------------------------------------------- savestates

@mcp.tool()
def save_state(name: str = "agent") -> list:
    """Snapshot the whole emulator under this name.

    Unlike the game's own save system this works anywhere, including mid-scene
    and mid-battle. Take one before anything you might want to undo.
    """
    return _act("/save", {"name": name}, note=f"save {name}")


@mcp.tool()
def load_state(name: str = "agent") -> list:
    """Restore a snapshot taken by save_state.

    Note that a snapshot taken during a cutscene restores into that cutscene,
    so movement will be ignored until you finish reading it.
    """
    return _act("/load", {"name": name}, note=f"load {name}")


@mcp.tool()
def list_states() -> str:
    """List the snapshots on disk with their sizes and timestamps."""
    return json.dumps(_call("GET", "/slots"), ensure_ascii=False, indent=2)


@mcp.tool()
def reset_game() -> list:
    """Reboot the emulator back to the title screen. Discards unsaved progress."""
    return _act("/reset", {}, note="reset")


if __name__ == "__main__":
    mcp.run()
