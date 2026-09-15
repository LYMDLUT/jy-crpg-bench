#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, realpath, lstat, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";
import {
  authorizeRequest, CLIENT_ORIGIN, gameEndpoint, MAX_BODY, MAX_RESPONSE,
  modelEndpoint, POLICY_VERSION, PolicyError, publicPrompt,
} from "./open-client-policy.mjs";

const root = dirname(dirname(fileURLToPath(import.meta.url)));

export function containerArgs({ name, image, clientDir, launchDir, runtime = "docker" }) {
  // No additional mounts, inherited environment, host namespaces or runtime
  // socket. Fixed flags, never operator- or model-supplied container options.
  return ["create", "--rm", "--interactive", "--pull=never", "--name", name,
    "--label=jy-crpg-bench.open-client=true",
    "--network=none", "--ipc=private", "--read-only", "--cap-drop=ALL",
    `--pid=${runtime === "podman" ? "private" : ""}`,
    "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=2g", "--cpus=2",
    "--user=1000:1000", "--workdir=/client", "--tmpfs=/tmp:rw,nosuid,nodev,size=256m,mode=1777",
    ...["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY",
      "http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy"].map(key => `--env=${key}=`),
    "--mount", `type=bind,source=${clientDir},target=/client`,
    "--mount", `type=bind,source=${launchDir},target=/launch,readonly`, image];
}

export function printArgs(args) {
  const result = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (["-p", "--print"].includes(arg)) continue;
    if (arg === "--mode") {
      if (!["text", "json"].includes(args[i + 1])) throw new Error("--mode must be text or json");
      result.push(arg, args[++i]);
    } else if (arg === "--") {
      const tail = args.slice(i + 1);
      if (tail.some(s => s.startsWith("@"))) throw new Error("host file arguments are disabled");
      result.push("--", ...tail);
      break;
    } else {
      if (arg.startsWith("-") || arg.startsWith("@")) throw new Error(`unsupported open-client argument: ${arg}`);
      result.push(arg);
    }
  }
  return result;
}

function command(binary, args, options = {}) {
  const r = spawnSync(binary, args, { encoding: "utf8", timeout: 30_000, ...options });
  if (r.error || r.status !== 0) throw new Error(`${binary} failed: ${r.error?.message || r.stderr}`);
  return r.stdout.trim();
}

async function privateDirectory(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  if ((await lstat(path)).isSymbolicLink() || await realpath(path) !== path)
    throw new Error(`run directories must not be symlinks: ${path}`);
}

async function launch() {
  const env = process.env;
  const runtime = env.QUNXIA_CONTAINER_RUNTIME || "docker";
  if (!["docker", "podman"].includes(runtime)) throw new Error("QUNXIA_CONTAINER_RUNTIME must be docker or podman");
  const image = env.QUNXIA_CLIENT_IMAGE || "jy-crpg-pi-client:0.84.4";
  if (image.startsWith("-")) throw new Error("invalid client image");
  if (!env.QUNXIA_LLM_MODEL?.includes("/")) throw new Error("set QUNXIA_LLM_MODEL=provider/model");
  const gameApi = gameEndpoint(env.QUNXIA_API || "");
  const llmBase = modelEndpoint(env.QUNXIA_LLM_BASE_URL || "");
  const userArgs = printArgs(process.argv.slice(2));
  const id = env.QUNXIA_RUN_ID || `${new Date().toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}`;
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) throw new Error("invalid QUNXIA_RUN_ID");
  if (![undefined, "0", "1"].includes(env.QUNXIA_RESUME)) throw new Error("QUNXIA_RESUME must be 0 or 1");
  const resume = env.QUNXIA_RESUME === "1";
  const runs = resolve(env.QUNXIA_RUNS_DIR || join(root, ".runs/pi"));
  await mkdir(runs, { recursive: true, mode: 0o700 });
  const runDir = join(await realpath(runs), id);
  if (runDir.includes(",")) throw new Error("run directory must not contain commas");
  const piVersion = JSON.parse(await readFile(join(root, "package.json"), "utf8"))
    .dependencies["@earendil-works/pi-coding-agent"];
  const runtimeVersion = command(runtime, ["version", "--format", "{{.Client.Version}}"]);
  const inspected = JSON.parse(command(runtime, ["image", "inspect", image]));
  if (!inspected[0]?.Id) throw new Error("build the open-client image first");
  const spec = { version: POLICY_VERSION, runtime, runtimeVersion, image,
    network: "none", transport: "stdio", cpus: 2, memory: "2g", pids: 128, hostProxyEnvironment: "cleared",
    mounts: { "/client": "client (read/write)", "/launch": "launch (read-only)" },
    tools: ["read", "write", "edit", "bash", "game_look", "game_press"],
  };
  if (resume) {
    const previous = JSON.parse(await readFile(join(runDir, "isolation.json"), "utf8"));
    if (JSON.stringify(previous) !== JSON.stringify(spec)) throw new Error("cannot resume: isolation configuration changed");
    await privateDirectory(runDir);
  }

  // Read the broker's clock before preparing the client. Boot, CV, and local
  // reasoning consume this same budget; no later response can extend it.
  const helpUrl = `${gameApi}/help?lang=${env.QUNXIA_BENCH_LANG || "zh"}`;
  const help = await fetch(helpUrl, { redirect: "error", signal: AbortSignal.timeout(30_000) });
  if (!help.ok) throw new Error(`session help returned HTTP ${help.status}`);
  const remainingText = help.headers.get("x-bench-remaining");
  if (!/^\d+$/.test(remainingText || "") || Number(remainingText) <= 0 || Number(remainingText) > 7 * 86400)
    throw new Error("open-client requires a live broker session with X-Bench-Remaining");
  const deadline = Date.now() + Number(remainingText) * 1000;
  const helpText = await help.text();
  const prepared = spawn(process.execPath, [join(root, "Scripts/prepare-pi-run.mjs")], {
    cwd: root, stdio: ["ignore", "ignore", "pipe"], env: {
      ...env, QUNXIA_ROOT: root, QUNXIA_RUN_DIR: runDir, QUNXIA_RUN_ID: id,
      QUNXIA_PI_PROFILE: "benchmark-open-client", QUNXIA_PI_VERSION: piVersion,
      QUNXIA_BENCH_LANG: env.QUNXIA_BENCH_LANG || "zh",
      QUNXIA_BENCH_HELP_URL: `data:text/plain,${encodeURIComponent(helpText)}`,
      QUNXIA_MODEL_REF: env.QUNXIA_LLM_MODEL, QUNXIA_API: gameApi,
      QUNXIA_LLM_BASE_URL: llmBase, QUNXIA_LLM_INPUT_JSON: env.QUNXIA_LLM_INPUT || "",
      QUNXIA_HARNESS_DIRTY: command("git", ["status", "--porcelain"], { cwd: root }) ? "1" : "0",
    },
  });
  let preparationError = "";
  prepared.stderr.on("data", data => { preparationError += data; });
  if ((await once(prepared, "exit"))[0] !== 0) throw new Error(preparationError);
  const manifest = JSON.parse(await readFile(join(runDir, "run.json"), "utf8"));
  if (JSON.stringify(manifest.tools) !== JSON.stringify(spec.tools)) throw new Error("open-client tools changed");
  const lock = join(runDir, ".open-client-active");
  await mkdir(lock); // Refuse two containers resuming the same files at once.
  const name = `qunxia-client-${randomUUID()}`;
  let child;
  let containerAttempted = false;
  let log;
  let timeout;
  let stopping = false;
  let timedOut = false;
  const active = new Map();
  const acks = new Map();
  const requests = new Set();
  let cleanupPromise;
  const cleanupContainer = () => cleanupPromise ??= (async () => {
    // PID 1 may ignore TERM, and Podman's rm --force otherwise waits ten
    // seconds. Kill the whole container immediately when its clock expires.
    for (const args of [["kill", "--signal=KILL", name], ["rm", "--force", name]]) {
      await new Promise(resolve => {
        const cleanup = spawn(runtime, args, { stdio: "ignore", timeout: 20_000 });
        cleanup.on("error", () => { child?.kill("SIGKILL"); resolve(); });
        cleanup.on("exit", () => resolve());
      });
    }
  })();
  const stop = () => {
    if (stopping) return;
    stopping = true;
    for (const controller of active.values()) controller.abort();
    for (const ack of acks.values()) ack();
    cleanupContainer();
  };
  const interrupted = () => stop();
  process.on("SIGINT", interrupted);
  process.on("SIGTERM", interrupted);
  try {
    const clientDir = join(runDir, "client");
    const launchDir = join(runDir, "launch");
    await privateDirectory(clientDir);
    await privateDirectory(launchDir);
    // Files in /client are never read or executed by the host, including on
    // resume. In particular, shell-writable Pi logs are not trusted billing.
    const models = JSON.parse(await readFile(join(runDir, "config/models.json"), "utf8"));
    for (const provider of Object.values(models.providers)) provider.baseUrl = `${CLIENT_ORIGIN}/llm`;
    await writeFile(join(launchDir, "models.json"), JSON.stringify(models), { mode: 0o644 });
    await writeFile(join(launchDir, "SYSTEM.md"), publicPrompt(
      await readFile(join(runDir, "config/SYSTEM.md"), "utf8"), gameApi), { mode: 0o644 });
    await writeFile(join(runDir, "isolation.json"), JSON.stringify(spec, null, 2) + "\n", { mode: 0o600 });
    // The UID mapping of a local Docker/Podman engine may differ from the
    // host UID. Only these two dedicated mounts are made accessible to it.
    const { chmod } = await import("node:fs/promises");
    await chmod(clientDir, 0o777);
    await chmod(launchDir, 0o755);
    console.log(`Pi ${piVersion} | run ${id} | profile benchmark-open-client\nRun state: ${runDir}`);
    if (stopping) return 130;
    if (env.QUNXIA_PREPARE_ONLY === "1") return 0;
    log = createWriteStream(join(runDir, "network.jsonl"), { flags: "a", mode: 0o600 });
    const policy = { gameApi, model: manifest.model, apiKey: env.QUNXIA_LLM_API_KEY || "local",
      agent: (env.QUNXIA_BENCH_AGENT || "pi").replace(/[^a-zA-Z0-9._-]/g, "").slice(0, 40) || "pi" };
    await writeFile(join(runDir, "launch.json"), JSON.stringify({ container: name, launcherPid: process.pid,
      startedAt: new Date().toISOString() }, null, 2) + "\n", { mode: 0o600 });
    if (stopping) return 130;
    // Create before starting: cancellation can now remove a known container,
    // even if attaching to its process has not finished yet.
    containerAttempted = true;
    command(runtime, containerArgs({ name, image: inspected[0].Id, clientDir, launchDir, runtime }));
    if (Date.now() >= deadline) { timedOut = true; return 124; }
    child = spawn(runtime, ["start", "--attach", "--interactive", name], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const completion = once(child, "exit");
    child.stderr.pipe(process.stderr);
    child.stdin.on("error", stop);
    const send = message => new Promise((resolve, reject) => {
      child.stdin.write(JSON.stringify(message) + "\n", error => error ? reject(error) : resolve());
    });
    async function request(message) {
      if (stopping) return;
      if (!Number.isSafeInteger(message.id) || message.id < 1 || active.has(message.id) || active.size >= 16)
        throw new Error("invalid bridge request");
      const controller = new AbortController();
      active.set(message.id, controller);
      const start = Date.now();
      let status = 502;
      let bytes = 0;
      let allowed = false;
      let sentHead = false;
      let completed = false;
      const timer = setTimeout(() => controller.abort(), 180_000);
      try {
        const target = authorizeRequest(message, policy);
        allowed = true;
        if (Date.now() >= deadline) throw new PolicyError("benchmark deadline reached");
        const response = await fetch(target.url, { ...target, redirect: "error", signal: controller.signal });
        status = response.status;
        const headers = { "content-type": response.headers.get("content-type") || "application/octet-stream" };
        if (response.headers.has("x-bench-remaining")) headers["x-bench-remaining"] = response.headers.get("x-bench-remaining");
        await send({ type: "head", id: message.id, status, headers });
        sentHead = true;
        const responseBody = message.path.startsWith("/api/help")
          ? [Buffer.from(publicPrompt(await response.text(), gameApi))] : response.body;
        for await (const chunk of responseBody) {
          bytes += chunk.length;
          if (bytes > MAX_RESPONSE) throw new Error("response too large");
          for (let offset = 0; offset < chunk.length; offset += 64 * 1024) {
            const ack = new Promise(resolve => {
              const done = () => { controller.signal.removeEventListener("abort", done); resolve(); };
              acks.set(message.id, done);
              controller.signal.addEventListener("abort", done, { once: true });
              if (controller.signal.aborted) done();
            });
            await send({ type: "chunk", id: message.id,
              data: Buffer.from(chunk.subarray(offset, offset + 64 * 1024)).toString("base64") });
            await ack;
            controller.signal.throwIfAborted();
          }
        }
        completed = true;
      } catch (error) {
        if (!sentHead && !stopping) {
          status = error instanceof PolicyError ? 403 : 502;
          await send({ type: "head", id: message.id, status, headers: { "content-type": "application/json" } });
          await send({ type: "chunk", id: message.id, data: Buffer.from(JSON.stringify({ ok: false,
            error: error instanceof PolicyError ? error.message : "upstream request failed" })).toString("base64") });
        }
      } finally {
        clearTimeout(timer);
        active.delete(message.id);
        acks.delete(message.id);
        log.write(JSON.stringify({ at: new Date(start).toISOString(), id: message.id,
          method: message.method, path: String(message.path).slice(0, 512), allowed, status, completed, bytes,
          durationMs: Date.now() - start }) + "\n");
        if (!stopping) await send({ type: "end", id: message.id });
      }
    }
    let buffer = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", data => {
      buffer += data;
      if (buffer.length > MAX_BODY * 2) return stop();
      let split;
      while ((split = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, split);
        buffer = buffer.slice(split + 1);
        try {
          const message = JSON.parse(line);
          if (message.type === "request") {
            const pending = request(message).catch(stop);
            requests.add(pending);
            pending.finally(() => requests.delete(pending));
          }
          else if (message.type === "ack") { acks.get(message.id)?.(); acks.delete(message.id); }
          else if (message.type === "cancel") { active.get(message.id)?.abort(); acks.get(message.id)?.(); }
          else if (message.type === "output" && ["stdout", "stderr"].includes(message.stream)) {
            process[message.stream].write(Buffer.from(message.data, "base64"));
          } else if (message.type !== "exit") stop();
        } catch { stop(); }
      }
    });
    timeout = setTimeout(() => { timedOut = true; stop(); }, Math.max(0, deadline - Date.now()));
    await send({ type: "init", args: ["--print", "--model", manifest.model.ref,
      "--thinking", manifest.model.thinkingLevel, "--session-dir", "/client/sessions", "--name", id,
      "--no-extensions", "--extension", "/opt/pi/extensions/qunxia/index.ts",
      "--no-skills", "--no-context-files", "--tools", spec.tools.join(","),
      ...(resume ? ["--continue"] : []), ...userArgs] });
    const [status] = await completion;
    await writeFile(join(runDir, "exit.json"), JSON.stringify({
      exitCode: status, timedOut, interrupted: stopping && !timedOut,
      finishedAt: new Date().toISOString(),
    }, null, 2) + "\n", { mode: 0o600 });
    return timedOut ? 124 : (status ?? 1);
  } finally {
    clearTimeout(timeout);
    process.off("SIGINT", interrupted);
    process.off("SIGTERM", interrupted);
    for (const controller of active.values()) controller.abort();
    for (const ack of acks.values()) ack();
    stopping = true;
    if (containerAttempted) await cleanupContainer();
    await Promise.allSettled([...requests]);
    if (log) await new Promise(resolve => log.end(resolve));
    await rm(lock, { recursive: true, force: true });
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = await launch(); }
  catch (error) { console.error(`open-client: ${error.message}`); process.exitCode = 1; }
}
