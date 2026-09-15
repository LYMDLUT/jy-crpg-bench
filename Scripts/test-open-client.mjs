import assert from "node:assert/strict";
import test from "node:test";
import { authorizeRequest, gameEndpoint, modelEndpoint, publicPrompt } from "./open-client-policy.mjs";
import { containerArgs, printArgs } from "./play-open-client.mjs";

const policy = {
  gameApi: "https://game.invalid/s/own/t/own-token/api", apiKey: "host-only-key", agent: "own-agent",
  model: { id: "fixture", api: "openai-completions", baseUrl: "https://model.invalid/v1" },
};
const route = (method, path, body) => authorizeRequest({ method, path, body: body && JSON.stringify(body) }, policy);

test("game forwarding is pinned to one session and discards caller identity and credentials", () => {
  for (const path of ["/api/screen", "/api/screen?format=png&scale=1", "/api/help?lang=zh", "/api/keys"]) {
    const result = route("GET", path);
    assert.equal(result.url, policy.gameApi + path.slice(4));
    assert.equal(result.headers["X-Agent"], "own-agent");
    assert.equal(result.headers.Authorization, undefined);
  }
  const result = authorizeRequest({ method: "POST", path: "/api/key?image=0&scale=1",
    body: '{"key":["kp3","kp3"],"hold":10}', headers: { "X-Agent": "other", "X-Reset-Token": "evil" },
    url: "https://elsewhere.invalid", token: "other-token" }, policy);
  assert.equal(result.headers["X-Agent"], "own-agent");
  assert.equal(result.headers["X-Reset-Token"], undefined);
  assert.equal(result.url, policy.gameApi + "/key?image=0&scale=1");
});

test("private, obsolete, spectator, cross-session and encoded routes fail closed", () => {
  for (const path of ["/api/status", "/api/history", "/api/recording", "/api/reset",
    "/api/snapshot", "/api/save", "/api/load", "/api/slots", "/api/catalog", "/api/sessions",
    "/api/keys/", "/api/screen/", "/api/../api/screen", "/api/%2e%2e/screen",
    "/api/%252e%252e/screen", "/api%2fscreen", "/api/screen#ignored", "/api/screen?token=secret",
    "/api/screen?spectate=1", "/api/screen?scale=2", "/api/screen?scale=1&scale=1",
    "/api/screen?format=svg", "/api/help?lang=zh&redirect=elsewhere",
    "/s/other/t/token/api/screen", "/ws", "https://elsewhere.invalid/api/screen", "//elsewhere.invalid/api/screen",
    "/api/\\elsewhere", "/api/screen\r\nHost:elsewhere"]) {
    assert.throws(() => route("GET", path), undefined, path);
  }
  for (const method of ["HEAD", "OPTIONS", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"]) {
    assert.throws(() => route(method, "/api/screen"));
  }
  for (const path of ["/api/keys", "/api/wait", "/api/reset", "/api/snapshot", "/usage", "/session"]) {
    assert.throws(() => route("POST", path, { key: "enter" }));
  }
  assert.throws(() => route("GET", "/api/screen", { token: "x" }));
});

test("key requests preserve the server contract without accepting hidden controls", () => {
  for (const body of [{ key: "enter" }, { key: ["kp3", "enter"], hold: 10 }]) {
    assert.equal(route("POST", "/api/key", body).body, JSON.stringify(body));
  }
  for (const body of [null, [], {}, { key: [] }, { key: 1 }, { key: ["up", 0] },
    { key: "up", hold: 0 }, { key: "up", hold: 4 }, { key: "up", hold: 1201 },
    { key: "up", hold: "10" }, { key: "up", snapshot: true }, { key: Array(101).fill("up") }]) {
    assert.throws(() => route("POST", "/api/key", body));
  }
});

test("inference routes only reach the declared provider model with host-held authentication", () => {
  const body = { model: "fixture", messages: [{ role: "user", content: "think" }],
    tools: [{ type: "function", function: { name: "read", parameters: { properties: { url: { type: "string" } } } } }] };
  const result = route("POST", "/llm/chat/completions", body);
  assert.equal(result.url, "https://model.invalid/v1/chat/completions");
  assert.equal(result.headers.Authorization, "Bearer host-only-key");
  assert.equal(result.headers["X-Agent"], undefined);
  const google = authorizeRequest({ method: "POST", path: "/llm/models/fixture:streamGenerateContent?alt=sse",
    body: JSON.stringify({ contents: [], tools: [{ functionDeclarations: [] }] }) }, {
    ...policy, model: { ...policy.model, api: "google-generative-ai" },
  });
  assert.equal(google.headers["x-goog-api-key"], "host-only-key");
  assert.equal(google.headers.Authorization, undefined);
  const response = authorizeRequest({ method: "POST", path: "/llm/responses",
    body: JSON.stringify({ model: "fixture", input: [{ type: "message", role: "user", content: [
      { type: "input_image", image_url: "data:image/png;base64,YQ==" },
    ] }], tools: [{ type: "function", name: "read" }] }) }, {
    ...policy, model: { ...policy.model, api: "openai-responses" },
  });
  assert.equal(response.url, "https://model.invalid/v1/responses");
});

test("inference cannot become a web proxy, file store or cross-run conversation reader", () => {
  for (const path of ["/llm/models", "/llm/files", "/llm/responses/other", "/llm/chat/completions?url=elsewhere",
    "/llm/chat/completions?key=other", "/llm/../api/screen"]) {
    assert.throws(() => route("POST", path, { model: "fixture" }));
  }
  for (const body of [{ model: "other" }, { model: "fixture", tools: [{ type: "web_search" }] },
    { model: "fixture", tools: [{ type: "mcp", server_url: "https://evil.invalid" }] },
    { model: "fixture", web_search_options: {} }, { model: "fixture", previous_response_id: "other" },
    { model: "fixture", conversation: "other" }, { model: "fixture", cachedContent: "other" },
    { model: "fixture", messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: "https://game.invalid/replay.png" } }] }] },
    { model: "fixture", input: [{ type: "input_image", image_url: "http://169.254.169.254/latest" }] },
    { model: "fixture", input: [{ type: "input_file", file_id: "other-file" }] }]) {
    assert.throws(() => route("POST", "/llm/chat/completions", body));
  }
  for (const body of [{ tools: [{ googleSearch: {} }] },
    { contents: [{ parts: [{ fileData: { fileUri: "https://game.invalid/replay.png" } }] }] }]) {
    assert.throws(() => authorizeRequest({ method: "POST", path: "/llm/models/fixture:streamGenerateContent",
      body: JSON.stringify(body) }, { ...policy, model: { ...policy.model, api: "google-generative-ai" } }));
  }
});

test("only tokenized game sessions and explicit provider bases are accepted", () => {
  assert.equal(gameEndpoint(policy.gameApi), policy.gameApi);
  for (const value of ["http://game.invalid/api", "https://game.invalid/s/other/api", "file:///api",
    `${policy.gameApi}?token=bad`, `${policy.gameApi}#bad`, "https://user:pass@game.invalid/s/a/t/b/api"]) {
    assert.throws(() => gameEndpoint(value));
  }
  for (const value of ["file:///model", "https://user:pass@model.invalid/v1", "https://model.invalid/v1?api_key=bad"]) {
    assert.throws(() => modelEndpoint(value));
  }
  assert.equal(modelEndpoint("https://model.invalid/v1/"), "https://model.invalid/v1");
  assert.equal(publicPrompt(`GET ${policy.gameApi}/screen`, policy.gameApi), "GET http://127.0.0.1:43123/api/screen");
});

test("container launch has only per-run mounts, no network or host environment", () => {
  const args = containerArgs({ name: "fixture", image: "sha256:fixture", clientDir: "/own/client", launchDir: "/own/launch" });
  for (const flag of ["--network=none", "--ipc=private", "--read-only", "--cap-drop=ALL",
    "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=2g", "--cpus=2", "--pull=never"])
    assert.ok(args.includes(flag), flag);
  assert.deepEqual(args.filter(s => s.startsWith("type=bind")), [
    "type=bind,source=/own/client,target=/client", "type=bind,source=/own/launch,target=/launch,readonly",
  ]);
  assert.doesNotMatch(args.join(" "), /--privileged|--pid=host|--network=host|docker.sock|podman.sock/);
  assert.ok(args.includes("--env=HTTP_PROXY="));
  assert.ok(args.includes("--pid="));
  assert.ok(containerArgs({ name: "fixture", image: "fixture", clientDir: "/a", launchDir: "/b",
    runtime: "podman" }).includes("--pid=private"));
  assert.ok(args.filter(arg => arg.startsWith("--env=")).every(arg => /^--env=[A-Z_]+=$/i.test(arg)));
});

test("open-client accepts prompts, not arbitrary Pi flags or host file attachments", () => {
  assert.deepEqual(printArgs(["-p", "--mode", "json", "play"]), ["--mode", "json", "play"]);
  for (const args of [["@/host/file"], ["--tools", "bash"], ["--extension", "/host/code"],
    ["--mode", "rpc"], ["--mode=json"], ["--", "@/host/file"]]) assert.throws(() => printArgs(args));
});
