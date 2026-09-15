import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const enabled = process.env.QUNXIA_TEST_CONTAINER === "1";
const runtime = process.env.QUNXIA_CONTAINER_RUNTIME || "docker";
const image = process.env.QUNXIA_CLIENT_IMAGE || "jy-crpg-pi-client:0.84.4";
const pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZkAAAAASUVORK5CYII=";

function client(directory, base, id, extra = {}) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("QUNXIA_")));
  const child = spawn(process.execPath, [join(root, "Scripts/play-open-client.mjs"), "-p", id], {
    env: { ...env, HTTP_PROXY: "http://fixture-proxy-secret.invalid:9",
      QUNXIA_CONTAINER_RUNTIME: runtime, QUNXIA_CLIENT_IMAGE: image,
      QUNXIA_LLM_MODEL: "fixture-google/gemini-3.8-flash", QUNXIA_LLM_BASE_URL: `${base}/v1beta`,
      QUNXIA_LLM_API: "google-generative-ai", QUNXIA_LLM_REASONING: "1", QUNXIA_THINKING: "high",
      QUNXIA_LLM_API_KEY: "host-only-model-key", QUNXIA_API: `${base}/s/${id}/t/token-${id}/api`,
      QUNXIA_RUNS_DIR: directory, QUNXIA_RUN_ID: id, QUNXIA_BENCH_AGENT: id,
      QUNXIA_HOST_SECRET: "must-not-enter-the-container", ...extra },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.on("data", data => { output += data; });
  child.stderr.on("data", data => { output += data; });
  const result = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", code => resolve({ code, output }));
  });
  return { child, result };
}

function probeScript(directory, base, id) {
  return `import json, os, pathlib, socket, urllib.request, urllib.error
import cv2, numpy as np
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
MARKER = 'before'
assert MARKER == ${JSON.stringify(id)}
assert os.environ['HOME'] == '/client/home'
assert os.environ['TMPDIR'] == '/client/tmp'
assert 'QUNXIA_HOST_SECRET' not in os.environ
assert os.environ['QUNXIA_LLM_API_KEY'] == 'client-gateway'
assert 'host-only-model-key' not in pathlib.Path('/client/config/models.json').read_text()
assert 'token-${id}' not in pathlib.Path('/client/config/SYSTEM.md').read_text()
for forbidden in [${JSON.stringify(root + "/server/server.py")}, ${JSON.stringify(directory + "/host-secret")},
                  '/var/run/docker.sock', '/run/podman/podman.sock', '/tmp/qunxia.png',
                  '/client/../client-B/workspace/secret.txt']:
    assert not pathlib.Path(forbidden).exists(), forbidden
pathlib.Path('/tmp/qunxia.png').write_text(MARKER)
assert pathlib.Path('/tmp/qunxia.png').read_text() == MARKER
assert b'bridge.mjs' in pathlib.Path('/proc/1/cmdline').read_bytes()
for environment in pathlib.Path('/proc').glob('[0-9]*/environ'):
    try:
        assert b'must-not-enter-the-container' not in environment.read_bytes()
        assert b'fixture-proxy-secret' not in environment.read_bytes()
    except (PermissionError, FileNotFoundError):
        pass
link = pathlib.Path('/client/workspace/source-link')
link.symlink_to(${JSON.stringify(root + "/server/server.py")})
assert not link.exists()
for host, port in [('127.0.0.1', ${new URL(base).port}), ('1.1.1.1', 80), ('169.254.169.254', 80)]:
    try:
        connection = socket.create_connection((host, port), timeout=0.3)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError('direct network escaped')
api = os.environ['QUNXIA_API']
for path in ['/history', '/recording', '/status', '/screen?spectate=1', '/../s/client-B/api/screen']:
    try:
        urllib.request.urlopen(api + path, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 403, (path, exc.code)
    else:
        raise AssertionError(path)
try:
    urllib.request.urlopen(api + '/keys', timeout=5)
except urllib.error.HTTPError as exc:
    assert exc.code == 502, exc.code
else:
    raise AssertionError('followed an upstream redirect')
brief = urllib.request.urlopen(api + '/help', timeout=5).read().decode()
assert 'token-${id}' not in brief
frames = list(pathlib.Path(os.environ['QUNXIA_SCREEN_DIR']).glob('*.png'))
assert frames
frame = np.asarray(Image.open(frames[0]).convert('RGB'))
gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
score = cv2.matchTemplate(gray, gray, cv2.TM_SQDIFF)
assert float(score.min()) == 0.0
pathlib.Path('/client/workspace/secret.txt').write_text(MARKER)
pathlib.Path('/client/tmp/local-only.txt').write_text(MARKER)
pathlib.Path('result.json').write_text(json.dumps({'marker': MARKER, 'cv': True, 'isolated': True}))
print('CV_AND_ISOLATION_OK_' + MARKER)
`;
}

test("two real Pi containers can read/write/edit/run CV but cannot see each other or the host", {
  skip: !enabled, timeout: 180_000,
}, async t => {
  const directory = await mkdtemp(join(tmpdir(), "qunxia-container-e2e-"));
  await writeFile(join(directory, "host-secret"), "host-source-and-credentials");
  const requests = [];
  const turns = new Map();
  let base;
  const server = createServer(async (req, res) => {
    let text = "";
    for await (const chunk of req) text += chunk;
    const body = text ? JSON.parse(text) : null;
    requests.push({ path: req.url, body, headers: req.headers });
    if (/\/api\/help(?:\?lang=zh)?$/.test(req.url)) {
      const prefix = `${base}${req.url.split("/api/help")[0]}/api`;
      res.setHeader("X-Bench-Remaining", "120");
      res.end(`# Fixture brief\nGET ${prefix}/screen\nPOST ${prefix}/key\n`);
    } else if (/\/api\/screen/.test(req.url)) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true, image: pixel, width: 1, height: 1 }));
    } else if (/\/api\/keys$/.test(req.url)) {
      res.writeHead(302, { Location: `${base}/forbidden-redirect-target` }).end();
    } else if (/\/api\/key\?/.test(req.url)) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true }));
    } else if (req.url === "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse") {
      const id = JSON.stringify(body.contents).includes("client-A") ? "client-A" : "client-B";
      const turn = (turns.get(id) || 0) + 1;
      turns.set(id, turn);
      const steps = [
        { name: "game_look", args: {} },
        { name: "write", args: { path: "probe.py", content: probeScript(directory, base, id) } },
        { name: "edit", args: { path: "probe.py", oldText: "MARKER = 'before'", newText: `MARKER = '${id}'` } },
        { name: "bash", args: { command: "python3 probe.py", timeout: 30 } },
        { name: "read", args: { path: "result.json" } },
        { name: "game_press", args: { key: "kp3" } },
      ];
      const parts = steps[turn - 1] ? [{ functionCall: steps[turn - 1] }] : [{ text: `Finished ${id}.` }];
      res.setHeader("Content-Type", "text/event-stream");
      res.end(`data: ${JSON.stringify({ candidates: [{ content: { role: "model", parts }, finishReason: "STOP" }],
        usageMetadata: { promptTokenCount: 100, candidatesTokenCount: 20, totalTokenCount: 120 } })}\n\n`);
    } else {
      res.writeHead(404).end();
    }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { server.closeAllConnections(); server.close(); });
  const a = client(directory, base, "client-A");
  const b = client(directory, base, "client-B");
  t.after(() => { if (a.child.exitCode === null) a.child.kill(); if (b.child.exitCode === null) b.child.kill(); });
  const results = await Promise.all([a.result, b.result]);
  for (const [index, id] of ["client-A", "client-B"].entries()) {
    assert.equal(results[index].code, 0, results[index].output);
    const result = JSON.parse(await readFile(join(directory, id, "client/workspace/result.json"), "utf8"));
    assert.deepEqual(result, { marker: id, cv: true, isolated: true });
    const saved = await readdir(join(directory, id, "client/workspace/frames"));
    assert.equal(saved.filter(s => s.endsWith(".png")).length, 1);
    const manifest = JSON.parse(await readFile(join(directory, id, "run.json"), "utf8"));
    assert.equal(manifest.profile, "benchmark-open-client");
    const isolation = JSON.parse(await readFile(join(directory, id, "isolation.json"), "utf8"));
    assert.equal(isolation.network, "none");
    assert.match(isolation.imageId, /^sha256:/);
    const log = (await readFile(join(directory, id, "network.jsonl"), "utf8")).trim().split("\n").map(JSON.parse);
    assert.equal(log.filter(r => !r.allowed && r.status === 403).length, 5);
    assert.equal(log.filter(r => r.path.startsWith("/api/key") && r.status === 200).length, 1);
    assert.equal(log.filter(r => r.path.startsWith("/llm/") && r.status === 200).length, 7);
    await assert.rejects(readFile(join(directory, id, "usage.json")), { code: "ENOENT" });
  }
  const models = requests.filter(req => req.path.startsWith("/v1beta/"));
  assert.equal(models.length, 14);
  for (const req of models) {
    assert.equal(req.headers["x-goog-api-key"], "host-only-model-key");
    assert.equal(req.body.generationConfig.thinkingConfig.thinkingLevel, "HIGH");
    const tools = req.body.tools.flatMap(t => t.functionDeclarations.map(f => f.name));
    assert.deepEqual(tools.sort(), ["bash", "edit", "game_look", "game_press", "read", "write"]);
  }
  const keys = requests.filter(req => req.path.includes("/api/key?"));
  assert.equal(keys.length, 2);
  for (const req of keys) {
    assert.equal(req.path, `/s/${req.headers["x-agent"]}/t/token-${req.headers["x-agent"]}/api/key?scale=1&image=0`);
    assert.deepEqual(req.body, { key: "kp3" });
  }
  assert.equal(requests.filter(req => /recording|history|status|usage|catalog/.test(req.path)).length, 0);
  assert.equal(requests.filter(req => req.path.includes("forbidden-redirect-target")).length, 0);
  const duplicate = await client(directory, base, "client-A").result;
  assert.notEqual(duplicate.code, 0);
  assert.match(duplicate.output, /already exists/);
  const changedSession = await client(directory, base, "client-A", { QUNXIA_RESUME: "1",
    QUNXIA_API: `${base}/s/other/t/other-token/api` }).result;
  assert.notEqual(changedSession.code, 0);
  assert.match(changedSession.output, /gameApi changed/);
  const resumed = await client(directory, base, "client-A", { QUNXIA_RESUME: "1" }).result;
  assert.equal(resumed.code, 0, resumed.output);
  assert.equal(turns.get("client-A"), 8);
  assert.equal(await readFile(join(directory, "client-A/client/workspace/secret.txt"), "utf8"), "client-A");
  // Retain failing fixtures for diagnosis; successful runs need no artifacts.
  await rm(directory, { recursive: true, force: true });
});

for (const api of ["openai-completions", "openai-responses"]) {
  test(`${api} streams through the real isolated Pi CLI with the six declared tools`, {
    skip: !enabled, timeout: 60_000,
  }, async t => {
    const directory = await mkdtemp(join(tmpdir(), "qunxia-openai-container-"));
    const calls = [];
    let base;
    const server = createServer(async (req, res) => {
      let text = "";
      for await (const chunk of req) text += chunk;
      if (req.url.includes("/api/help")) {
        res.setHeader("X-Bench-Remaining", "45");
        res.end(`GET ${base}/s/run/t/token-run/api/screen\nPOST ${base}/s/run/t/token-run/api/key`);
      } else if (req.url === (api === "openai-completions" ? "/v1/chat/completions" : "/v1/responses")) {
        const body = JSON.parse(text);
        calls.push({ body, headers: req.headers });
        res.setHeader("Content-Type", "text/event-stream");
        if (api === "openai-completions") {
          res.end(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", model: "gpt-5.6-fixture",
            choices: [{ index: 0, delta: { role: "assistant", content: "OpenAI fixture finished." }, finish_reason: "stop" }],
            usage: { prompt_tokens: 100, completion_tokens: 10, total_tokens: 110 } })}\n\ndata: [DONE]\n\n`);
        } else {
          const item = { type: "message", id: "msg_1", role: "assistant", status: "completed",
            content: [{ type: "output_text", text: "OpenAI fixture finished.", annotations: [] }] };
          const events = [
            { type: "response.created", response: { id: "resp_1", status: "in_progress" } },
            { type: "response.output_item.added", output_index: 0, item: { ...item, content: [] } },
            { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "OpenAI fixture finished." },
            { type: "response.output_item.done", output_index: 0, item },
            { type: "response.completed", response: { id: "resp_1", status: "completed", output: [item],
              usage: { input_tokens: 100, output_tokens: 10, total_tokens: 110 } } },
          ];
          res.end(events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(""));
        }
      } else res.writeHead(404).end();
    });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    base = `http://127.0.0.1:${server.address().port}`;
    t.after(() => { server.closeAllConnections(); server.close(); });
    const run = client(directory, base, "run", { QUNXIA_LLM_API: api,
      QUNXIA_LLM_MODEL: "fixture-openai/gpt-5.6-fixture", QUNXIA_LLM_BASE_URL: `${base}/v1`,
      QUNXIA_LLM_SUPPORTS_REASONING_EFFORT: "1" });
    t.after(() => { if (run.child.exitCode === null) run.child.kill(); });
    const result = await run.result;
    assert.equal(result.code, 0, result.output);
    assert.match(result.output, /OpenAI fixture finished/);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].headers.authorization, "Bearer host-only-model-key");
    assert.equal(calls[0].body.model, "gpt-5.6-fixture");
    assert.equal(api === "openai-completions" ? calls[0].body.reasoning_effort : calls[0].body.reasoning.effort, "high");
    assert.deepEqual(calls[0].body.tools.map(t => t.function?.name || t.name).sort(),
      ["bash", "edit", "game_look", "game_press", "read", "write"]);
    await rm(directory, { recursive: true, force: true });
  });
}

test("the broker deadline terminates local shell work and its container", {
  skip: !enabled, timeout: 30_000,
}, async t => {
  const directory = await mkdtemp(join(tmpdir(), "qunxia-container-deadline-"));
  let base;
  let inferenceCalls = 0;
  const server = createServer(async (req, res) => {
    for await (const _chunk of req) { /* drain the request */ }
    if (req.url.includes("/api/help")) {
      res.setHeader("X-Bench-Remaining", "3");
      res.end(`GET ${base}/s/deadline/t/token-deadline/api/screen\nPOST ${base}/s/deadline/t/token-deadline/api/key`);
    } else {
      inferenceCalls++;
      res.setHeader("Content-Type", "text/event-stream");
      res.end(`data: ${JSON.stringify({ candidates: [{ content: { role: "model",
        parts: [{ functionCall: { name: "bash", args: { command: "sleep 60" } } }] }, finishReason: "STOP" }] })}\n\n`);
    }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { server.closeAllConnections(); server.close(); });
  const started = Date.now();
  const run = client(directory, base, "deadline");
  t.after(() => { if (run.child.exitCode === null) run.child.kill(); });
  const result = await run.result;
  assert.equal(result.code, 124, result.output);
  assert.equal(inferenceCalls, 1, result.output);
  assert.ok(Date.now() - started < 12_000);
  const exit = JSON.parse(await readFile(join(directory, "deadline/exit.json"), "utf8"));
  assert.equal(exit.timedOut, true);
  await rm(directory, { recursive: true, force: true });
});
