/**
 * Game tools for 金庸群俠傳. Each action applies input to the emulator, waits
 * for the screen to settle, and hands the resulting frame back to the model as
 * an image, so one tool call is one action and one observation.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const API = process.env.QUNXIA_API ?? "http://127.0.0.1:8765";
const SCALE = Number(process.env.QUNXIA_SCALE ?? "2");

type Content = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };

async function call(method: string, path: string, body?: unknown, signal?: AbortSignal) {
  const res = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  return (await res.json()) as Record<string, any>;
}

function offline(err: unknown) {
  return {
    content: [{
      type: "text" as const,
      text:
        `The game is not reachable at ${API} (${err}). It must be running: start it ` +
        `with ./Scripts/run.sh from the repo and give it about 14 seconds to reach ` +
        `the title screen.`,
    }],
    details: { error: String(err) },
    isError: true,
  };
}

/** Turn an API response into a status line plus the screen. */
function frame(res: Record<string, any>, note: string) {
  const bits: string[] = [];
  if (res.ok === false) bits.push("FAILED");
  if ("changed" in res) {
    bits.push(res.changed ? "screen changed" : "screen did NOT change (no visible effect)");
  }
  if (res.error) bits.push(String(res.error));
  bits.push(`${res.width}x${res.height}`);

  const content: Content[] = [{ type: "text", text: `${note} | ${bits.join(" | ")}` }];
  if (typeof res.image === "string") {
    content.push({ type: "image", data: res.image.split(",", 2)[1], mimeType: "image/png" });
  }
  return { content, details: { ok: res.ok !== false, changed: res.changed, frame: res.frame } };
}

export default function (pi: ExtensionAPI) {
  const act = async (path: string, body: unknown, note: string, signal?: AbortSignal) => {
    try {
      return frame(await call("POST", `${path}?scale=${SCALE}`, body, signal), note);
    } catch (err) {
      return offline(err);
    }
  };

  pi.registerTool({
    name: "game_look",
    label: "Look",
    description:
      "Look at the current game screen without pressing anything. Use it to re-read a " +
      "screen you did not finish reading, or to re-orient after losing track of where you are.",
    promptSnippet: "Look at the current game screen",
    parameters: Type.Object({
      scale: Type.Optional(Type.Number({
        description: "1-6, enlarges the 320x200 frame. Raise it if Chinese glyphs are hard to read.",
      })),
    }),
    async execute(_id, params, signal) {
      try {
        return frame(await call("GET", `/state?scale=${params.scale ?? SCALE}`, undefined, signal), "look");
      } catch (err) {
        return offline(err);
      }
    },
  });

  pi.registerTool({
    name: "game_press",
    label: "Press",
    description:
      "Press one key and return the screen it produced. Keys: up, down, left, right, " +
      "enter, space, esc, y, n, a-z, 0-9, f1-f12, tab, backspace, or a combo like 'alt+x'. " +
      "Use times to repeat the same key, for example walking several tiles or advancing " +
      "several lines of dialogue. Remember that during a cutscene every key only advances " +
      "the dialogue.",
    promptSnippet: "Press a key in the game",
    parameters: Type.Object({
      key: Type.String({ description: "Key name, e.g. up, enter, esc, y" }),
      times: Type.Optional(Type.Number({ description: "Repeat count, default 1" })),
      hold: Type.Optional(Type.Number({ description: "Frames to hold the key, default 4" })),
      stable: Type.Optional(Type.Number({
        description: "Frames the picture must hold still before the screenshot. Raise if you get a half-written dialogue line.",
      })),
    }),
    async execute(_id, params, signal) {
      const times = params.times ?? 1;
      const q = params.stable ? `&stable=${params.stable}` : "";
      const note = times > 1 ? `${params.key} x${times}` : params.key;
      const body = times > 1
        ? { keys: Array(times).fill(params.key), hold: params.hold }
        : { key: params.key, hold: params.hold };
      const path = times > 1 ? "/keys" : "/key";
      try {
        return frame(await call("POST", `${path}?scale=${SCALE}${q}`, body, signal), note);
      } catch (err) {
        return offline(err);
      }
    },
  });

  pi.registerTool({
    name: "game_press_sequence",
    label: "Press sequence",
    description:
      "Press several different keys in order and return only the final screen. Use it for " +
      "a menu path you are sure about, such as ['esc','down','down','enter']. Prefer " +
      "game_press when you are unsure what a screen will do, because here you do not see " +
      "the intermediate frames.",
    promptSnippet: "Press a sequence of keys in the game",
    parameters: Type.Object({
      keys: Type.Array(Type.String(), { description: "Key names in order" }),
      gap: Type.Optional(Type.Number({ description: "Frames between keys, default 6" })),
    }),
    execute: (_id, params, signal) =>
      act("/keys", { keys: params.keys, gap: params.gap }, params.keys.join(" "), signal),
  });

  pi.registerTool({
    name: "game_move",
    label: "Move",
    description:
      "Walk. One step turns the character to face that direction and moves one tile if it " +
      "is not blocked, so walking into a person or object is how you talk to it. If nothing " +
      "moves you are either blocked by scenery or still inside a cutscene.",
    promptSnippet: "Walk in the game world",
    parameters: Type.Object({
      direction: Type.String({ description: "up, down, left or right" }),
      steps: Type.Optional(Type.Number({ description: "Tiles to walk, default 1" })),
    }),
    execute: (_id, params, signal) => {
      const dir = params.direction.toLowerCase();
      if (!["up", "down", "left", "right"].includes(dir)) {
        return Promise.resolve({
          content: [{ type: "text" as const, text: "direction must be up, down, left or right" }],
          details: {},
          isError: true,
        });
      }
      const steps = Math.max(1, params.steps ?? 1);
      return act("/keys", { keys: Array(steps).fill(dir), gap: 6 }, `move ${dir} x${steps}`, signal);
    },
  });

  pi.registerTool({
    name: "game_type",
    label: "Type",
    description:
      "Type a literal string, one key per character. The character-name prompt runs the " +
      "game's own 注音 IME, so send zhuyin keys rather than pinyin: 'j;6' produces the " +
      "candidate list for ㄨㄤˊ, then press the digit for the character you want.",
    promptSnippet: "Type a string into the game",
    parameters: Type.Object({ text: Type.String() }),
    execute: (_id, params, signal) => act("/text", { text: params.text }, `type ${params.text}`, signal),
  });

  pi.registerTool({
    name: "game_wait",
    label: "Wait",
    description:
      "Let the game run without pressing anything, then return the screen. Use during boot, " +
      "scene transitions, battle animations and travel on the world map.",
    promptSnippet: "Let the game run for a while",
    parameters: Type.Object({
      ms: Type.Optional(Type.Number({ description: "Milliseconds, default 1000" })),
    }),
    execute: (_id, params, signal) =>
      act("/wait", { ms: params.ms ?? 1000 }, `wait ${params.ms ?? 1000}ms`, signal),
  });

  pi.registerTool({
    name: "game_save",
    label: "Save",
    description:
      "Snapshot the whole emulator under a name. Unlike the game's own save system this " +
      "works anywhere, including mid-scene and mid-battle. Take one before anything risky.",
    promptSnippet: "Snapshot the emulator state",
    parameters: Type.Object({ name: Type.String({ description: "Snapshot name" }) }),
    execute: (_id, params, signal) => act("/save", { name: params.name }, `save ${params.name}`, signal),
  });

  pi.registerTool({
    name: "game_load",
    label: "Load",
    description:
      "Restore a snapshot taken by game_save. A snapshot taken during a cutscene restores " +
      "into that cutscene, so movement stays ignored until you finish reading it.",
    promptSnippet: "Restore an emulator snapshot",
    parameters: Type.Object({ name: Type.String({ description: "Snapshot name" }) }),
    execute: (_id, params, signal) => act("/load", { name: params.name }, `load ${params.name}`, signal),
  });

  pi.registerTool({
    name: "game_saves",
    label: "List saves",
    description: "List the emulator snapshots on disk with their sizes and timestamps.",
    promptSnippet: "List emulator snapshots",
    parameters: Type.Object({}),
    async execute(_id, _params, signal) {
      try {
        const res = await call("GET", "/slots", undefined, signal);
        return { content: [{ type: "text" as const, text: JSON.stringify(res, null, 2) }], details: res };
      } catch (err) {
        return offline(err);
      }
    },
  });
}
