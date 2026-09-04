import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const prepare = join(root, "Scripts", "prepare-pi-run.mjs");
const readProfile = join(root, "Scripts", "read-pi-profile.mjs");
const playAgent = join(root, "Scripts", "play-agent.sh");
const benchmarkHelp = [
  "# Benchmark help fixture",
  "## API",
  "GET  http://game.invalid/api/screen look, pressing nothing",
  "POST http://game.invalid/api/key one key",
  "POST http://game.invalid/api/keys several keys",
  "POST http://game.invalid/api/wait let the game run",
  "## 移動：請用九宮數字鍵的名稱",
].join("\n");
const benchmarkHelpUrl = `data:text/plain;charset=utf-8,${encodeURIComponent(benchmarkHelp)}`;

function invoke(runsDir, runId, profile = "strict", resume = false, overrides = {}) {
  const runDir = join(runsDir, runId);
  return spawnSync(process.execPath, [prepare], {
    encoding: "utf8",
    env: {
      ...process.env,
      QUNXIA_ROOT: root,
      QUNXIA_RUN_DIR: runDir,
      QUNXIA_RUN_ID: runId,
      QUNXIA_PI_PROFILE: profile,
      QUNXIA_PI_VERSION: "0.84.4",
      QUNXIA_BENCH_LANG: "zh",
      QUNXIA_BENCH_HELP_URL: benchmarkHelpUrl,
      QUNXIA_LLM_BASE_URL: "http://model.invalid/v1",
      QUNXIA_MODEL_REF: "local-test/test-model",
      QUNXIA_LLM_PROVIDER: "local-test",
      QUNXIA_LLM_MODEL: "test-model",
      QUNXIA_LLM_INPUT_JSON: '["text","image"]',
      QUNXIA_LLM_CONTEXT: "128000",
      QUNXIA_LLM_MAX_TOKENS: "8192",
      QUNXIA_LLM_API: "openai-completions",
      QUNXIA_LLM_REASONING: "1",
      QUNXIA_LLM_SUPPORTS_REASONING_EFFORT: "1",
      QUNXIA_THINKING: profile === "benchmark" ? "max" : "",
      QUNXIA_API: "http://game.invalid",
      QUNXIA_HARNESS_DIRTY: "0",
      QUNXIA_RESUME: resume ? "1" : "0",
      ...overrides,
    },
  });
}

test("strict runs have separate state and contain no credential", async () => {
  const runsDir = await mkdtemp(join(tmpdir(), "qunxia-pi-runs-"));
  for (const id of ["run-a", "run-b"]) {
    const result = invoke(runsDir, id);
    assert.equal(result.status, 0, result.stderr);
  }

  const a = JSON.parse(await readFile(join(runsDir, "run-a", "run.json"), "utf8"));
  const b = JSON.parse(await readFile(join(runsDir, "run-b", "run.json"), "utf8"));
  assert.notEqual(a.runId, b.runId);
  assert.equal(a.paths.help, null);
  assert.equal(a.scale, 1);
  assert.equal(a.observeAfterAction, true);
  assert.equal(a.model.thinkingLevel, null);
  assert.equal(a.model.ref, "local-test/test-model");
  assert.equal(a.model.provider, "local-test");
  assert.deepEqual(a.extensions, ["qunxia"]);
  assert.deepEqual(a.tools, [
    "game_look",
    "game_press",
    "game_press_sequence",
    "game_move",
    "game_wait",
    "game_save",
    "game_load",
    "game_saves",
  ]);
  const models = await readFile(join(runsDir, "run-a", "config", "models.json"), "utf8");
  assert.match(models, /\$QUNXIA_LLM_API_KEY/);
  assert.doesNotMatch(models, /secret-for-test/);
  const resolvedProfile = JSON.parse(
    await readFile(join(runsDir, "run-a", "config", "profile.json"), "utf8"),
  );
  assert.deepEqual(resolvedProfile.tools, a.tools);
});

test("existing runs require explicit compatible resume", async () => {
  const runsDir = await mkdtemp(join(tmpdir(), "qunxia-pi-resume-"));
  assert.equal(invoke(runsDir, "resume-a").status, 0);

  const duplicate = invoke(runsDir, "resume-a");
  assert.notEqual(duplicate.status, 0);
  assert.match(duplicate.stderr, /already exists/);

  const resumed = invoke(runsDir, "resume-a", "strict", true);
  assert.equal(resumed.status, 0, resumed.stderr);
  const manifest = JSON.parse(await readFile(join(runsDir, "resume-a", "run.json"), "utf8"));
  assert.equal(manifest.resumeCount, 1);

  const changedModel = invoke(runsDir, "resume-a", "strict", true, {
    QUNXIA_LLM_MODEL: "different-model",
  });
  assert.notEqual(changedModel.status, 0);
  assert.match(changedModel.stderr, /model configuration changed/);

  const changedThinking = invoke(runsDir, "resume-a", "strict", true, {
    QUNXIA_THINKING: "max",
  });
  assert.notEqual(changedThinking.status, 0);
  assert.match(changedThinking.stderr, /model configuration changed/);
});

test("unknown profiles fail closed", async () => {
  const runsDir = await mkdtemp(join(tmpdir(), "qunxia-pi-profile-"));
  const result = invoke(runsDir, "unknown-a", "not-a-profile");
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unknown QUNXIA_PI_PROFILE/);
});

test("profile lookup explains an unknown profile", () => {
  const result = spawnSync(process.execPath, [
    readProfile,
    join(root, "pi-agent", "profiles.json"),
    "not-a-profile",
  ], {
    encoding: "utf8",
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unknown QUNXIA_PI_PROFILE not-a-profile/);
  assert.match(result.stderr, /available profiles:/);
});

test("the launcher requires a full provider/model reference", () => {
  const result = spawnSync("zsh", [playAgent], {
    encoding: "utf8",
    env: {
      ...process.env,
      QUNXIA_LLM_BASE_URL: "http://model.invalid/v1",
      QUNXIA_LLM_MODEL: "model-without-provider",
    },
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /must include non-empty provider and model names/);
});

test("benchmark profile exposes only broker-supported game tools", async () => {
  const runsDir = await mkdtemp(join(tmpdir(), "qunxia-pi-benchmark-"));
  const result = invoke(runsDir, "benchmark-a", "benchmark");
  assert.equal(result.status, 0, result.stderr);
  const manifest = JSON.parse(await readFile(join(runsDir, "benchmark-a", "run.json"), "utf8"));
  assert.deepEqual(manifest.tools, [
    "game_look",
    "game_press",
    "game_press_sequence",
    "game_wait",
  ]);
  assert.equal(manifest.tools.some((name) => name.startsWith("game_save")), false);
  assert.equal(manifest.scale, 1);
  assert.equal(manifest.observeAfterAction, false);
  assert.equal(manifest.prompt.source, "session-help");
  assert.equal(manifest.prompt.language, "zh");
  assert.equal(manifest.prompt.helpChars, benchmarkHelp.length);
  assert.equal(manifest.model.api, "openai-completions");
  assert.equal(manifest.model.reasoning, true);
  assert.equal(manifest.model.supportsReasoningEffort, true);
  assert.equal(manifest.model.thinkingLevel, "max");
  const prompt = await readFile(join(runsDir, "benchmark-a", "config", "SYSTEM.md"), "utf8");
  assert.match(prompt, /BEGIN SESSION-SPECIFIC BENCHMARK BRIEF/);
  assert.match(prompt, /session is isolated/);
  assert.match(prompt, /POST http:\/\/game\.invalid\/api\/key/);
  assert.doesNotMatch(prompt, /\{BASE\}/);
  assert.doesNotMatch(prompt, /Entering a Chinese name/);
});

test("game press leaves the server tap duration authoritative", async () => {
  const extension = await readFile(
    join(root, "pi-agent", "extensions", "qunxia", "index.ts"),
    "utf8",
  );
  assert.match(extension, /Omit to use the game server's safe tap default/);
  assert.doesNotMatch(extension, /default 4/);
});

test("benchmark thinking must be explicit and supported", () => {
  const runsDir = join(tmpdir(), `qunxia-pi-thinking-${process.pid}-${Date.now()}`);
  const missing = invoke(runsDir, "missing-thinking", "benchmark", false, {
    QUNXIA_THINKING: "",
  });
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /explicit QUNXIA_THINKING/);

  const unsupported = invoke(runsDir, "unsupported-thinking", "benchmark", false, {
    QUNXIA_LLM_REASONING: "0",
  });
  assert.notEqual(unsupported.status, 0);
  assert.match(unsupported.stderr, /requires a reasoning model/);
});

test("benchmark profile fails closed without complete session help", async () => {
  const runsDir = await mkdtemp(join(tmpdir(), "qunxia-pi-missing-help-"));
  const missing = invoke(runsDir, "missing-help", "benchmark", false, {
    QUNXIA_BENCH_HELP_URL: "",
  });
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /requires QUNXIA_BENCH_HELP_URL/);

  const incomplete = invoke(runsDir, "incomplete-help", "benchmark", false, {
    QUNXIA_BENCH_HELP_URL: "data:text/plain,incomplete",
  });
  assert.notEqual(incomplete.status, 0);
  assert.match(incomplete.stderr, /benchmark help is incomplete/);
});
