// The trusted host decides every destination. The container can request a
// route and a body, never a host, token, forwarded header or arbitrary URL.
export const POLICY_VERSION = "open-client-v1";
export const MAX_BODY = 32 * 1024 * 1024;
export const MAX_RESPONSE = 128 * 1024 * 1024;
export const CLIENT_ORIGIN = "http://127.0.0.1:43123";

export class PolicyError extends Error {}

export function gameEndpoint(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password
      || url.search || url.hash || !/^\/s\/[a-zA-Z0-9_-]+\/t\/[a-zA-Z0-9_-]+\/api$/.test(url.pathname)) {
    throw new Error("QUNXIA_API must be the broker's tokenized session base_url plus /api");
  }
  return url.href;
}

export function modelEndpoint(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("QUNXIA_LLM_BASE_URL must be an HTTP(S) base URL without credentials or query");
  }
  return url.href.replace(/\/$/, "");
}

function object(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function check(condition, message) {
  if (!condition) throw new PolicyError(message);
}

function queryOnly(url, allowed) {
  const seen = new Set();
  for (const [key, value] of url.searchParams) {
    check(!seen.has(key) && allowed[key]?.includes(value), "query parameter is not allowed");
    seen.add(key);
  }
}

// Providers' hosted search, URL fetches, file stores and built-in tools are
// outside this protocol. Local function tools and inline images remain valid.
function inlineInputs(value) {
  if (Array.isArray(value)) return value.forEach(inlineInputs);
  if (!object(value)) return;
  check(!["input_file", "file", "file_data"].includes(value.type), "provider file inputs are disabled");
  for (const [key, item] of Object.entries(value)) {
    check(!["file_id", "fileId", "file_uri", "fileUri", "file_url", "fileUrl",
      "fileData", "file_data", "cachedContent", "previous_response_id", "conversation"].includes(key),
    "provider-side files and conversation state are disabled");
    if (key === "url" || (key === "image_url" && typeof item === "string")) {
      check(typeof item === "string" && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(item),
        "only inline image URLs are allowed");
    }
    inlineInputs(item);
  }
}

function modelBody(body, model) {
  check(object(body), "model request must be a JSON object");
  if (model.api !== "google-generative-ai") {
    check(body.model === model.id, "only the declared model is allowed");
  }
  if (body.tools !== undefined) {
    check(Array.isArray(body.tools), "invalid tools");
    for (const tool of body.tools) {
      check(object(tool), "invalid tool");
      if (model.api === "google-generative-ai") {
        check(Object.keys(tool).every(key => key === "functionDeclarations")
          && Array.isArray(tool.functionDeclarations), "hosted model tools are disabled");
      } else {
        check(tool.type === "function", "hosted model tools are disabled");
      }
    }
  }
  // Inspect actual inputs, not function JSON schemas, which legitimately
  // contain property names such as url or file_id.
  for (const key of ["messages", "input", "contents", "systemInstruction"]) {
    inlineInputs(body[key]);
  }
  for (const key of ["previous_response_id", "conversation", "cachedContent", "background", "web_search_options"])
    check(body[key] === undefined || body[key] === false, "provider-side state is disabled");
}

export function authorizeRequest(message, { gameApi, model, apiKey, agent }) {
  check(object(message) && ["GET", "POST"].includes(message.method), "method is not allowed");
  const path = message.path;
  check(typeof path === "string" && /^\/(api|llm)\//.test(path)
    && !/[\\#\s]/.test(path) && !/%(?:2e|2f|5c)/i.test(path), "path is not allowed");
  const url = new URL(path, CLIENT_ORIGIN);
  check(url.origin === CLIENT_ORIGIN && url.pathname === path.split("?", 1)[0], "noncanonical path");
  const body = message.body ?? "";
  check(typeof body === "string" && Buffer.byteLength(body) <= MAX_BODY, "request body too large");
  const headers = { "Content-Type": "application/json" };
  let target;
  if (url.pathname.startsWith("/api/")) {
    const route = `${message.method} ${url.pathname}`;
    if (route === "GET /api/screen") {
      queryOnly(url, { scale: ["1"], format: ["png", "jpeg", "webp"] });
    } else if (route === "GET /api/help") {
      queryOnly(url, { lang: ["zh", "en"] });
    } else if (route === "GET /api/keys") {
      queryOnly(url, {});
    } else if (route === "POST /api/key") {
      queryOnly(url, { scale: ["1"], image: ["0", "1"] });
      let data;
      try { data = JSON.parse(body); } catch { throw new PolicyError("key body must be JSON"); }
      check(object(data) && Object.keys(data).every(k => ["key", "hold"].includes(k)), "invalid key body");
      const keys = Array.isArray(data.key) ? data.key : [data.key];
      check(keys.length >= 1 && keys.length <= 100
        && keys.every(k => typeof k === "string" && k.length >= 1 && k.length <= 32), "invalid keys");
      check(data.hold === undefined || (Number.isInteger(data.hold) && data.hold >= 5 && data.hold <= 1200),
        "invalid hold");
    } else {
      throw new PolicyError("game route is not allowed");
    }
    check(message.method !== "GET" || body === "", "GET body is not allowed");
    headers["X-Agent"] = agent;
    target = gameApi + path.slice("/api".length);
  } else {
    check(message.method === "POST", "model method is not allowed");
    const expected = {
      "openai-completions": "/llm/chat/completions",
      "openai-responses": "/llm/responses",
      "google-generative-ai": `/llm/models/${encodeURIComponent(model.id)}:streamGenerateContent`,
    }[model.api];
    check(url.pathname === expected, "model route is not allowed");
    queryOnly(url, model.api === "google-generative-ai" ? { alt: ["sse"] } : {});
    let data;
    try { data = JSON.parse(body); } catch { throw new PolicyError("model body must be JSON"); }
    modelBody(data, model);
    if (model.api === "google-generative-ai") headers["x-goog-api-key"] = apiKey;
    else headers.Authorization = `Bearer ${apiKey}`;
    target = model.baseUrl + path.slice("/llm".length);
  }
  return { url: target, method: message.method, headers, body: body || undefined };
}

export function publicPrompt(text, gameApi) {
  return text.split(gameApi.slice(0, -4)).join(CLIENT_ORIGIN);
}
