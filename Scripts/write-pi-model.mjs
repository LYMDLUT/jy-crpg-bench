#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

const output = process.argv[2];
if (!output) throw new Error("usage: write-pi-model.mjs OUTPUT");

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function integer(name, fallback, minimum, maximum) {
  const raw = process.env[name] ?? String(fallback);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function bool(name, fallback = false) {
  const raw = (process.env[name] ?? String(fallback)).toLowerCase();
  if (["1", "true", "yes"].includes(raw)) return true;
  if (["0", "false", "no"].includes(raw)) return false;
  throw new Error(`${name} must be true or false`);
}

const baseUrl = required("QUNXIA_LLM_BASE_URL").replace(/\/+$/, "");
const parsedUrl = new URL(baseUrl);
if (!["http:", "https:"].includes(parsedUrl.protocol)) {
  throw new Error("QUNXIA_LLM_BASE_URL must use http or https");
}

const model = required("QUNXIA_LLM_MODEL");
const api = process.env.QUNXIA_LLM_API ?? "openai-completions";
const supportedApis = new Set([
  "openai-completions", "openai-responses", "anthropic-messages",
  "google-generative-ai",
]);
if (!supportedApis.has(api)) throw new Error(`unsupported QUNXIA_LLM_API: ${api}`);

// Accept text,image as well as the historical '"text", "image"' spelling.
const input = [...new Set((process.env.QUNXIA_LLM_INPUT ?? "text,image")
  .replace(/[\[\]"'\s]/g, "").split(",").filter(Boolean))];
if (!input.includes("text") || input.some((kind) => !["text", "image"].includes(kind))) {
  throw new Error("QUNXIA_LLM_INPUT must be text or text,image");
}
const contextWindow = integer("QUNXIA_LLM_CONTEXT", 128000, 1024, 10_000_000);
const maxTokens = integer("QUNXIA_LLM_MAX_TOKENS", 8192, 256, 1_000_000);
if (maxTokens > contextWindow) {
  throw new Error("QUNXIA_LLM_MAX_TOKENS cannot exceed QUNXIA_LLM_CONTEXT");
}

const config = {
  providers: {
    qunxia: {
      baseUrl,
      api,
      apiKey: "$QUNXIA_LLM_API_KEY",
      compat: {
        supportsDeveloperRole: bool("QUNXIA_LLM_DEVELOPER_ROLE"),
        supportsReasoningEffort: bool("QUNXIA_LLM_REASONING_EFFORT"),
      },
      models: [{
        id: model,
        name: model,
        reasoning: bool("QUNXIA_LLM_REASONING"),
        input,
        contextWindow,
        maxTokens,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      }],
    },
  },
};

fs.mkdirSync(path.dirname(output), { recursive: true });
const temporary = `${output}.tmp-${process.pid}`;
fs.writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
fs.renameSync(temporary, output);
