#!/usr/bin/env node
import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

const required = [
  "QUNXIA_ROOT",
  "QUNXIA_RUN_DIR",
  "QUNXIA_RUN_ID",
  "QUNXIA_PI_PROFILE",
  "QUNXIA_PI_VERSION",
  "QUNXIA_LLM_BASE_URL",
  "QUNXIA_LLM_MODEL",
  "QUNXIA_LLM_INPUT_JSON",
  "QUNXIA_LLM_CONTEXT",
  "QUNXIA_API",
];

for (const name of required) {
  if (!process.env[name]) throw new Error(`${name} is required`);
}

const root = process.env.QUNXIA_ROOT;
const runDir = process.env.QUNXIA_RUN_DIR;
const runId = process.env.QUNXIA_RUN_ID;
const profile = process.env.QUNXIA_PI_PROFILE;
const resume = process.env.QUNXIA_RESUME === "1";
const configDir = join(runDir, "config");
const sessionDir = join(runDir, "sessions");
const workspaceDir = join(runDir, "workspace");
const manifestPath = join(runDir, "run.json");
let existingManifest = null;
if (resume) {
  try {
    existingManifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`cannot resume ${runId}: ${error.message}`);
  }
}

const profileFile = join(root, "pi-agent", "profiles.json");
const profiles = JSON.parse(await readFile(profileFile, "utf8"));
const profileDefinition = profiles[profile];
if (!profileDefinition) {
  throw new Error(
    `unknown QUNXIA_PI_PROFILE ${profile}; available profiles: ${Object.keys(profiles).join(", ")}`,
  );
}
if (!["standalone", "session-help"].includes(profileDefinition.prompt)) {
  throw new Error(`profile ${profile} has an invalid prompt source`);
}
if (!Number.isInteger(profileDefinition.scale) || profileDefinition.scale !== 1) {
  throw new Error(`profile ${profile} must use the native observation scale`);
}
if (typeof profileDefinition.observeAfterAction !== "boolean") {
  throw new Error(`profile ${profile} must declare observeAfterAction`);
}

const extensionTools = {
  qunxia: [
    "game_look",
    "game_press",
    "game_press_sequence",
    "game_move",
    "game_wait",
    "game_save",
    "game_load",
    "game_saves",
  ],
};
if (!Array.isArray(profileDefinition.extensions) || !profileDefinition.extensions.includes("qunxia")) {
  throw new Error(`profile ${profile} must load the qunxia extension`);
}
if (profileDefinition.extensions.some((name) => !(name in extensionTools))) {
  throw new Error(`profile ${profile} contains an unknown extension`);
}
const allowedTools = new Set(profileDefinition.extensions.flatMap((name) => extensionTools[name]));
if (!Array.isArray(profileDefinition.tools) || profileDefinition.tools.length === 0) {
  throw new Error(`profile ${profile} must declare at least one tool`);
}
if (profileDefinition.tools.some((name) => !allowedTools.has(name))) {
  throw new Error(`profile ${profile} contains a tool not supplied by its isolated extensions`);
}
if (new Set(profileDefinition.tools).size !== profileDefinition.tools.length) {
  throw new Error(`profile ${profile} contains duplicate tools`);
}

let input;
try {
  input = JSON.parse(process.env.QUNXIA_LLM_INPUT_JSON);
} catch (error) {
  throw new Error(`QUNXIA_LLM_INPUT must be a JSON array: ${error.message}`);
}
if (
  !Array.isArray(input) ||
  input.length === 0 ||
  new Set(input).size !== input.length ||
  input.some((item) => !["text", "image"].includes(item))
) {
  throw new Error('QUNXIA_LLM_INPUT must contain only "text" and "image"');
}

const contextWindow = Number(process.env.QUNXIA_LLM_CONTEXT);
if (!Number.isSafeInteger(contextWindow) || contextWindow <= 0) {
  throw new Error("QUNXIA_LLM_CONTEXT must be a positive integer");
}

let benchmarkHelp = null;
let systemPrompt;
let promptMetadata;
if (profileDefinition.prompt === "session-help") {
  const language = resume
    ? existingManifest?.prompt?.language
    : (process.env.QUNXIA_BENCH_LANG || "zh");
  const helpUrl = resume
    ? existingManifest?.prompt?.url
    : process.env.QUNXIA_BENCH_HELP_URL;

  if (resume) {
    try {
      benchmarkHelp = await readFile(join(configDir, "benchmark-help.md"), "utf8");
    } catch {
      throw new Error(`cannot resume ${runId}: benchmark help snapshot is missing`);
    }
  } else {
    if (!helpUrl) throw new Error(`profile ${profile} requires QUNXIA_BENCH_HELP_URL`);
    let response;
    try {
      response = await fetch(helpUrl, { signal: AbortSignal.timeout(30_000) });
    } catch (error) {
      throw new Error(`could not fetch benchmark help: ${error.message}`);
    }
    if (!response.ok) {
      throw new Error(`could not fetch benchmark help: HTTP ${response.status}`);
    }
    benchmarkHelp = await response.text();
  }

  const markers = language.toLowerCase().startsWith("zh")
    ? [
        "## API",
        "`POST {BASE}/api/key`",
        "`POST {BASE}/api/keys`",
        "`POST {BASE}/api/wait`",
        "## 移動：請用九宮數字鍵的名稱",
      ]
    : [
        "## API",
        "`POST {BASE}/api/key`",
        "`POST {BASE}/api/keys`",
        "`POST {BASE}/api/wait`",
        "## Movement: use the numpad names",
      ];
  const missing = markers.filter((marker) => !benchmarkHelp.includes(marker));
  if (missing.length) {
    throw new Error(`benchmark help is incomplete; missing: ${missing.join(", ")}`);
  }

  const adapter = await readFile(join(root, "pi-agent", "BENCHMARK.md"), "utf8");
  systemPrompt = `${adapter}\n\n${benchmarkHelp}\n--- END SESSION-SPECIFIC BENCHMARK BRIEF ---\n`;
  promptMetadata = {
    source: "session-help",
    url: helpUrl,
    language,
    helpChars: benchmarkHelp.length,
  };
} else {
  systemPrompt = await readFile(join(root, "pi-agent", "SYSTEM.md"), "utf8");
  promptMetadata = { source: "pi-agent/SYSTEM.md" };
}

const identity = {
  runId,
  profile,
  piPackage: "@earendil-works/pi-coding-agent",
  piVersion: process.env.QUNXIA_PI_VERSION,
  nodeVersion: process.version,
  harnessDirty: process.env.QUNXIA_HARNESS_DIRTY === "1",
  gameApi: process.env.QUNXIA_API,
  scale: profileDefinition.scale,
  observeAfterAction: profileDefinition.observeAfterAction,
  extensions: profileDefinition.extensions,
  tools: profileDefinition.tools,
  prompt: promptMetadata,
  model: {
    provider: "qunxia",
    id: process.env.QUNXIA_LLM_MODEL,
    baseUrl: process.env.QUNXIA_LLM_BASE_URL,
    input,
    contextWindow,
    maxTokens: 8192,
  },
};

const models = {
  providers: {
    qunxia: {
      baseUrl: identity.model.baseUrl,
      api: "openai-completions",
      apiKey: "$QUNXIA_LLM_API_KEY",
      compat: { supportsDeveloperRole: false, supportsReasoningEffort: false },
      models: [{
        id: identity.model.id,
        name: identity.model.id,
        input: identity.model.input,
        contextWindow: identity.model.contextWindow,
        maxTokens: identity.model.maxTokens,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      }],
    },
  },
};

if (resume) {
  const manifest = existingManifest;

  for (const field of [
    "runId",
    "profile",
    "piPackage",
    "piVersion",
    "nodeVersion",
    "harnessDirty",
    "gameApi",
    "scale",
    "observeAfterAction",
  ]) {
    if (manifest[field] !== identity[field]) {
      throw new Error(`cannot resume ${runId}: ${field} changed`);
    }
  }
  for (const field of ["extensions", "tools", "prompt"]) {
    if (JSON.stringify(manifest[field]) !== JSON.stringify(identity[field])) {
      throw new Error(`cannot resume ${runId}: ${field} changed`);
    }
  }
  if (JSON.stringify(manifest.model) !== JSON.stringify(identity.model)) {
    throw new Error(`cannot resume ${runId}: model configuration changed`);
  }

  manifest.resumeCount = (manifest.resumeCount || 0) + 1;
  manifest.lastResumedAt = new Date().toISOString();
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`${runDir}\n`);
  process.exit(0);
}

try {
  await mkdir(runDir, { recursive: false, mode: 0o700 });
} catch (error) {
  if (error?.code === "EEXIST") {
    throw new Error(`run ${runId} already exists; set QUNXIA_RESUME=1 to continue it`);
  }
  await mkdir(dirname(runDir), { recursive: true, mode: 0o700 });
  await mkdir(runDir, { recursive: false, mode: 0o700 });
}

await Promise.all([
  mkdir(configDir, { mode: 0o700 }),
  mkdir(sessionDir, { mode: 0o700 }),
  mkdir(workspaceDir, { mode: 0o700 }),
]);

await writeFile(join(configDir, "SYSTEM.md"), systemPrompt, { mode: 0o600 });
if (benchmarkHelp !== null) {
  await writeFile(join(configDir, "benchmark-help.md"), benchmarkHelp, { mode: 0o600 });
}
await writeFile(join(configDir, "models.json"), `${JSON.stringify(models, null, 2)}\n`, { mode: 0o600 });
await writeFile(
  join(configDir, "profile.json"),
  `${JSON.stringify(profileDefinition, null, 2)}\n`,
  { mode: 0o600 },
);
for (const extension of profileDefinition.extensions) {
  await cp(join(root, "pi-agent", "extensions", extension), join(configDir, extension), {
    recursive: true,
  });
}
const manifest = {
  ...identity,
  createdAt: new Date().toISOString(),
  resumeCount: 0,
  paths: {
    config: "config",
    sessions: "sessions",
    workspace: "workspace",
    help: benchmarkHelp !== null ? "config/benchmark-help.md" : null,
  },
};
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${runDir}\n`);
