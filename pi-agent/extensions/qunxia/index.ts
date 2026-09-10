/**
 * Game tools for 金庸群俠傳. Standalone profiles return the frame after each
 * action; benchmark profiles preserve the broker's action/look split.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const API = (process.env.QUNXIA_API ?? "http://127.0.0.1:8765").replace(/\/+$/, "");
const rawScale = Number(process.env.QUNXIA_SCALE ?? "1");
const SCALE = Number.isFinite(rawScale) ? Math.min(6, Math.max(1, Math.trunc(rawScale))) : 1;
const AGENT = (process.env.QUNXIA_AGENT ?? "pi").replace(/[^a-zA-Z0-9_.-]/g, "").slice(0, 40) || "pi";
const OBSERVE_AFTER_ACTION = process.env.QUNXIA_OBSERVE_AFTER_ACTION !== "0";
const ACTION_RESULT = OBSERVE_AFTER_ACTION
  ? "The resulting visible frame is returned."
  : "Only action metadata is returned; call game_look when you need the next visible frame.";

type Content = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };

class GameApiError extends Error {
  status: number | undefined;
  hint: string | undefined;
  constructor(message: string, status?: number, hint?: string) {
    super(message);
    this.status = status;
    this.hint = hint;
  }
}

async function call(method: string, path: string, body?: unknown, signal?: AbortSignal) {
  const res = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Agent": AGENT },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const text = await res.text();
  let payload: Record<string, any>;
  try {
    const parsed = JSON.parse(text);
    payload = parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, any>
      : { ok: false, error: "game API returned a non-object response" };
  } catch {
    payload = {
      ok: false,
      error: `game API returned HTTP ${res.status} with a non-JSON response`,
    };
  }
  // The end of a benchmark run is an answer, not a request failure: its 410
  // body is the summary the brief tells the model to wait for, so it passes
  // through even though the status code is not 2xx.
  if (payload.ended) return payload;
  if (!res.ok) {
    payload.ok = false;
    payload.error ??= `game API returned HTTP ${res.status}`;
  }
  if (payload.ok === false) {
    throw new GameApiError(
      String(payload.error ?? `game API returned HTTP ${res.status}`),
      res.status,
      typeof payload.hint === "string" && payload.hint ? payload.hint : undefined);
  }
  return payload;
}

function toolFailure(err: unknown) {
  if (err instanceof GameApiError) {
    const status = err.status !== undefined ? ` (HTTP ${err.status})` : "";
    const hint = err.hint ? ` ${err.hint}` : "";
    return {
      content: [{
        type: "text" as const,
        text: `The game rejected the request: ${err.message}${status}.${hint}`,
      }],
      details: { error: String(err.message), status: err.status, hint: err.hint },
      isError: true,
    };
  }
  return {
    content: [{
      type: "text" as const,
      text:
        `The game is not reachable at ${API} (${err}). Check QUNXIA_API and the ` +
        `selected game or benchmark session.`,
    }],
    details: { error: String(err) },
    isError: true,
  };
}

/** Turn an API response into a status line plus the screen. */
function frame(res: Record<string, any>, note: string) {
  if (res.ended) {
    return {
      content: [{
        type: "text" as const,
        text: `BENCHMARK ENDED | ${JSON.stringify({
          reason: res.reason,
          why: res.why,
          message: res.message,
          actions: res.actions,
          played_seconds: res.played_seconds ?? res.played,
          video_url: res.video_url,
          video_pending: res.video_pending,
        })}`,
      }],
      details: res,
    };
  }
  const bits: string[] = [];
  if (res.ok === false) bits.push("FAILED");
  if (res.error) bits.push(String(res.error));
  if (res.image_error) bits.push(`image unavailable: ${res.image_error}`);
  if (res.observation === "follow-up") {
    bits.push("follow-up screenshot (not atomic on a shared session)");
  }
  if (res.width !== undefined && res.height !== undefined) {
    bits.push(`${res.width}x${res.height}`);
  }

  const content: Content[] = [{ type: "text", text: `${note} | ${bits.join(" | ")}` }];
  if (typeof res.image === "string" && res.image.includes(",")) {
    const [header, data] = res.image.split(",", 2);
    const mimeType = header.match(/^data:([^;]+);base64$/)?.[1] ?? "image/png";
    if (data) content.push({ type: "image", data, mimeType });
  }
  return {
    content,
    details: { ok: res.ok !== false, frame: res.frame },
  };
}

export default function (pi: ExtensionAPI) {
  const act = async (
    path: string,
    body: unknown,
    note: string,
    signal?: AbortSignal,
    query = "",
  ) => {
    try {
      // The server encodes a frame only when asked. Asking inside the action
      // keeps action and observation atomic; older servers that ignore the
      // flag fall back to a separate look below.
      const image = OBSERVE_AFTER_ACTION ? "&image=1" : "&image=0";
      const action = await call("POST", `${path}?scale=${SCALE}${image}${query}`, body, signal);
      if (action.ended || action.ok === false) {
        return frame(action, note);
      }
      if (!OBSERVE_AFTER_ACTION) {
        const { image: _ignored, ...metadata } = action;
        return frame(metadata, note);
      }
      if (typeof action.image === "string") return frame(action, note);
      const screen = await call("GET", `/screen?scale=${SCALE}`, undefined, signal);
      if (screen.ended) return frame(screen, note);
      return frame({
        ...screen,
        ok: action.ok !== false && screen.ok !== false,
        action: action.action,
        actionFrame: action.frame,
      }, note);
    } catch (err) {
      return toolFailure(err);
    }
  };

  pi.registerTool({
    name: "game_look",
    label: "Look",
    description:
      "Look at the current game screen without pressing anything. Use it to re-read a " +
      "screen you did not finish reading, or to re-orient after losing track of where you are.",
    promptSnippet: "Look at the current game screen",
    parameters: Type.Object({}),
    async execute(_id, params, signal) {
      try {
        return frame(await call("GET", `/screen?scale=${SCALE}`, undefined, signal), "look");
      } catch (err) {
        return toolFailure(err);
      }
    },
  });

  pi.registerTool({
    name: "game_press",
    label: "Press",
    description:
      "Press one key, or several in order. Movement keys are kp7, kp9, kp1 and kp3 " +
      "(preferred), with left, up, down and right as the same four axes. Other keys: " +
      "enter, space, esc, y, n, a-z, 0-9, f1-f12, tab, backspace. A repeat is a list of " +
      "the same key, for example [\"kp3\", \"kp3\", \"kp3\"] to walk three tiles or " +
      "[\"enter\", \"enter\"] to advance two lines; a menu path is a list such as " +
      "[\"esc\", \"down\", \"down\", \"enter\"]. The reply says what was pressed and " +
      `nothing about what the screen did: read the next picture. ${ACTION_RESULT}`,
    promptSnippet: "Press one or more keys in the game",
    parameters: Type.Object({
      key: Type.Union([
        Type.String({ minLength: 1, maxLength: 32, description: "A key name, e.g. kp3, enter, esc, y" }),
        Type.Array(Type.String({ minLength: 1, maxLength: 32 }), {
          minItems: 1, maxItems: 100, description: "Key names pressed in order",
        }),
      ]),
      hold: Type.Optional(Type.Integer({ minimum: 5, maximum: 1200,
        description: "Emulated frames to hold each key, 5 or more. Below five the game can " +
          "consume the press and release together and the key never registers. " +
          "Omit to use the game server's tap default of 10; a long hold walks several tiles.",
      })),
    }),
    async execute(_id, params, signal) {
      const keys = Array.isArray(params.key) ? params.key : [params.key];
      const body: Record<string, unknown> = { key: params.key };
      if (params.hold !== undefined) body.hold = params.hold;
      return act("/key", body, keys.join(" "), signal);
    },
  });

  pi.registerTool({
    name: "game_save",
    label: "Save",
    description:
      "Request an emulator snapshot under a name, including scene or battle state. " +
      "Check that saving succeeded before relying on it; the game's own save menu " +
      "is limited to the world map.",
    promptSnippet: "Snapshot the emulator state",
    parameters: Type.Object({ name: Type.String({ minLength: 1, maxLength: 64, description: "Snapshot name" }) }),
    execute: (_id, params, signal) => act("/save", { name: params.name }, `save ${params.name}`, signal),
  });

  pi.registerTool({
    name: "game_load",
    label: "Load",
    description:
      "Restore a snapshot taken by game_save, including its current dialogue, menu, " +
      "or animation state. Inspect the restored screen before choosing the next action.",
    promptSnippet: "Restore an emulator snapshot",
    parameters: Type.Object({ name: Type.String({ minLength: 1, maxLength: 64, description: "Snapshot name" }) }),
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
        return {
          content: [{ type: "text" as const, text: JSON.stringify(res, null, 2) }],
          details: res,
        };
      } catch (err) {
        return toolFailure(err);
      }
    },
  });
}
