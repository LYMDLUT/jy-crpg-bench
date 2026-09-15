import assert from "node:assert/strict";
import test from "node:test";
import { authorizeRequest } from "./open-client-policy.mjs";

const policy = {
  gameApi: "https://game.invalid/s/own/t/token/api", apiKey: "host-key", agent: "own-agent",
  model: { id: "fixture", api: "openai-completions", baseUrl: "https://model.invalid/v1" },
};
const request = (method, path, body) => authorizeRequest({ method, path,
  body: body ? JSON.stringify(body) : "" }, policy);

test("game requests stay inside the current session's visual and keyboard API", () => {
  const key = request("POST", "/api/key", { key: ["kp3", "enter"] });
  assert.equal(key.url, policy.gameApi + "/key");
  assert.equal(key.headers["X-Agent"], "own-agent");
  assert.equal(request("GET", "/api/screen").url, policy.gameApi + "/screen");
  for (const path of ["/api/status", "/api/recording", "/api/reset", "/api/screen?spectate=1",
    "/api/%2e%2e/screen", "/s/other/api/screen", "//other.invalid/api/screen"]) {
    assert.throws(() => request("GET", path));
  }
  assert.throws(() => request("POST", "/api/key", { key: "up", snapshot: true }));
});

test("inference cannot read another model, remote files or hosted search", () => {
  const call = body => request("POST", "/llm/chat/completions", body);
  assert.equal(call({ model: "fixture", messages: [] }).headers.Authorization, "Bearer host-key");
  for (const body of [{ model: "other" }, { model: "fixture", previous_response_id: "other-run" },
    { model: "fixture", tools: [{ type: "web_search" }] },
    { model: "fixture", input: [{ type: "input_file", file_id: "other-file" }] },
    { model: "fixture", input: [{ type: "input_image", image_url: "https://game.invalid/replay.png" }] }]) {
    assert.throws(() => call(body));
  }
});
