import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const options = { skip: process.env.QUNXIA_TEST_CONTAINER !== "1", timeout: 90_000 };
const pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZkAAAAASUVORK5CYII=";

function client(t, directory, base, id) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("QUNXIA_")));
  const child = spawn(process.execPath, [join(root, "Scripts/play-open-client.mjs"), "-p", id], {
    env: { ...env, QUNXIA_CONTAINER_RUNTIME: process.env.QUNXIA_CONTAINER_RUNTIME || "docker",
      QUNXIA_CLIENT_IMAGE: process.env.QUNXIA_CLIENT_IMAGE || "jy-crpg-pi-client:0.84.4",
      QUNXIA_LLM_MODEL: "fixture-google/gemini-3.8-flash", QUNXIA_LLM_BASE_URL: `${base}/v1beta`,
      QUNXIA_LLM_API: "google-generative-ai", QUNXIA_LLM_REASONING: "1", QUNXIA_THINKING: "high",
      QUNXIA_LLM_API_KEY: "host-only-key", QUNXIA_API: `${base}/s/${id}/t/token-${id}/api`,
      QUNXIA_RUNS_DIR: directory, QUNXIA_RUN_ID: id, QUNXIA_HOST_SECRET: "host-secret" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.on("data", data => { output += data; });
  child.stderr.on("data", data => { output += data; });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  return new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", code => resolve({ code, output }));
  });
}

async function fixture(t, seconds, respond) {
  let base;
  const calls = [];
  const server = createServer(async (req, res) => {
    let text = "";
    for await (const chunk of req) text += chunk;
    const body = text ? JSON.parse(text) : null;
    calls.push({ path: req.url, body });
    if (req.url.includes("/api/help")) {
      const api = `${base}${req.url.split("/api/help")[0]}/api`;
      res.setHeader("X-Bench-Remaining", String(seconds));
      res.end(`GET ${api}/screen\nPOST ${api}/key`);
    } else if (req.url.includes("/api/screen")) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true, image: pixel, width: 1, height: 1 }));
    } else if (req.url.includes("/api/key?")) {
      res.end('{"ok":true}');
    } else if (req.url.startsWith("/v1beta/")) {
      res.setHeader("Content-Type", "text/event-stream");
      res.end(`data: ${JSON.stringify({ candidates: [{ content: { role: "model",
        parts: respond(body, base) }, finishReason: "STOP" }] })}\n\n`);
    } else res.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { base, calls };
}

test("concurrent clients can use file tools and CV without host or cross-run access", options, async t => {
  const directory = await mkdtemp(join(tmpdir(), "qunxia-client-smoke-"));
  const turns = new Map();
  const { base, calls } = await fixture(t, 60, (body, endpoint) => {
    const id = JSON.stringify(body.contents).includes("client-A") ? "client-A" : "client-B";
    const turn = turns.get(id) || 0;
    turns.set(id, turn + 1);
    const code = `import os, pathlib, socket, urllib.request, urllib.error
import cv2, numpy as np
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
marker = 'before'
assert marker == '${id}'
assert os.environ['HOME'] == '/client/home' and os.environ['TMPDIR'] == '/client/tmp'
assert 'QUNXIA_HOST_SECRET' not in os.environ
assert not pathlib.Path(${JSON.stringify(root + "/server/server.py")}).exists()
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/tmp/qunxia.png').exists()
pathlib.Path('/tmp/qunxia.png').write_text(marker)
assert b'bridge.mjs' in pathlib.Path('/proc/1/cmdline').read_bytes()
for host, port in [('127.0.0.1', ${new URL(endpoint).port}), ('1.1.1.1', 80)]:
    try:
        socket.create_connection((host, port), timeout=0.2)
    except OSError:
        pass
    else:
        raise AssertionError('network escaped')
for path in ['/history', '/../s/other/api/screen']:
    try:
        urllib.request.urlopen(os.environ['QUNXIA_API'] + path, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError(path)
frame = next(pathlib.Path(os.environ['QUNXIA_SCREEN_DIR']).glob('*.png'))
gray = cv2.cvtColor(np.asarray(Image.open(frame).convert('RGB')), cv2.COLOR_RGB2GRAY)
assert cv2.matchTemplate(gray, gray, cv2.TM_SQDIFF).min() == 0
pathlib.Path('result.txt').write_text(marker)
`;
    const steps = [
      { name: "game_look", args: {} },
      { name: "write", args: { path: "probe.py", content: code } },
      { name: "edit", args: { path: "probe.py", oldText: "marker = 'before'", newText: `marker = '${id}'` } },
      { name: "bash", args: { command: "python3 probe.py", timeout: 20 } },
      { name: "read", args: { path: "result.txt" } },
      { name: "game_press", args: { key: "kp3" } },
    ];
    return steps[turn] ? [{ functionCall: steps[turn] }] : [{ text: "Finished." }];
  });
  const ids = ["client-A", "client-B"];
  const results = await Promise.all(ids.map(id => client(t, directory, base, id)));
  for (const [i, id] of ids.entries()) {
    assert.equal(results[i].code, 0, results[i].output);
    assert.equal(await readFile(join(directory, id, "client/workspace/result.txt"), "utf8"), id);
  }
  assert.equal(calls.filter(c => c.path.includes("/api/key?")).length, 2);
  assert.equal(calls.filter(c => /history|other/.test(c.path)).length, 0);
  await rm(directory, { recursive: true, force: true });
});

test("the broker deadline stops a long local shell command", options, async t => {
  const directory = await mkdtemp(join(tmpdir(), "qunxia-client-deadline-"));
  const { base } = await fixture(t, 3, () => [{ functionCall: {
    name: "bash", args: { command: "sleep 60" },
  } }]);
  const started = Date.now();
  const result = await client(t, directory, base, "deadline");
  assert.equal(result.code, 124, result.output);
  assert.ok(Date.now() - started < 12_000);
  const exit = JSON.parse(await readFile(join(directory, "deadline/exit.json"), "utf8"));
  assert.equal(exit.timedOut, true);
  await rm(directory, { recursive: true, force: true });
});
