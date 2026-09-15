// The container has no network interface except loopback. HTTP requests to
// this local adapter cross stdio; the host independently authorizes each one.
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { cp, mkdir } from "node:fs/promises";
import { once } from "node:events";

const MAX_BODY = 32 * 1024 * 1024;
const pending = new Map();
let nextId = 0;
let pi;
let server;
let started = false;

function send(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

async function start(args) {
  if (started || !Array.isArray(args)) throw new Error("invalid initialization");
  started = true;
  for (const name of ["home", "config", "sessions", "workspace", "tmp", "cache"]) {
    await mkdir(`/client/${name}`, { recursive: true, mode: 0o700 });
  }
  for (const name of ["SYSTEM.md", "models.json"]) {
    await cp(`/launch/${name}`, `/client/config/${name}`);
  }
  server = createServer(async (req, res) => {
    if (pending.size >= 16) return res.writeHead(429).end("too many requests");
    const chunks = [];
    let size = 0;
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > MAX_BODY) return res.writeHead(413).end("request too large");
        chunks.push(chunk);
      }
      const id = ++nextId;
      pending.set(id, res);
      res.on("close", () => {
        if (pending.delete(id)) send({ type: "cancel", id });
      });
      send({ type: "request", id, method: req.method, path: req.url,
        body: Buffer.concat(chunks).toString("utf8") });
    } catch {
      res.destroy();
    }
  });
  server.on("connect", (_req, socket) => socket.destroy());
  server.on("upgrade", (_req, socket) => socket.destroy());
  server.listen(43123, "127.0.0.1");
  await once(server, "listening");
  pi = spawn(process.execPath, ["/opt/pi/node_modules/.bin/pi", ...args], {
    cwd: "/client/workspace",
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      PATH: "/usr/local/bin:/usr/bin:/bin", HOME: "/client/home", SHELL: "/bin/bash",
      TMPDIR: "/client/tmp", TMP: "/client/tmp", TEMP: "/client/tmp",
      XDG_CONFIG_HOME: "/client/home/.config", XDG_CACHE_HOME: "/client/cache",
      XDG_DATA_HOME: "/client/home/.local/share", XDG_STATE_HOME: "/client/home/.local/state",
      LANG: "C.UTF-8", TERM: "dumb", PI_CODING_AGENT_DIR: "/client/config", PI_OFFLINE: "1",
      QUNXIA_API: "http://127.0.0.1:43123/api", QUNXIA_SCALE: "1",
      QUNXIA_OBSERVE_AFTER_ACTION: "0", QUNXIA_LLM_API_KEY: "client-gateway",
      QUNXIA_SCREEN_DIR: "/client/workspace/frames",
    },
  });
  for (const stream of ["stdout", "stderr"]) {
    pi[stream].on("data", chunk => send({ type: "output", stream, data: chunk.toString("base64") }));
  }
  pi.on("error", () => { send({ type: "exit", code: 1 }); process.exit(1); });
  pi.on("exit", code => { send({ type: "exit", code: code ?? 1 }); process.exit(code ?? 1); });
}

async function receive(message) {
  if (message.type === "init") return start(message.args);
  const res = pending.get(message.id);
  if (!res) return;
  if (message.type === "head") res.writeHead(message.status, message.headers);
  if (message.type === "chunk") {
    if (!res.write(Buffer.from(message.data, "base64"))) await once(res, "drain");
    send({ type: "ack", id: message.id });
  }
  if (message.type === "end") { pending.delete(message.id); res.end(); }
}

let buffer = "";
let queue = Promise.resolve();
process.stdin.setEncoding("utf8");
process.stdin.on("data", data => {
  buffer += data;
  if (buffer.length > 2 * MAX_BODY) process.exit(1);
  let split;
  while ((split = buffer.indexOf("\n")) !== -1) {
    const line = buffer.slice(0, split);
    buffer = buffer.slice(split + 1);
    queue = queue.then(() => receive(JSON.parse(line))).catch(() => process.exit(1));
  }
});
process.stdin.on("end", () => process.exit(1));
