import base64
import http.server
import json
import os
import pathlib
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE = base64.b64encode(b"synthetic-game-frame").decode()


def sse_chunk(model, *, tool=None, tool_args=None, text=None, finish="stop"):
    if tool:
        delta = {
            "role": "assistant",
            "tool_calls": [{
                "index": 0, "id": f"call-{tool}", "type": "function",
                "function": {"name": tool,
                             "arguments": json.dumps(tool_args or {})},
            }],
        }
        finish = "tool_calls"
    else:
        delta = {"role": "assistant", "content": text}
    chunks = [
        {
            "id": f"response-{model}", "object": "chat.completion.chunk",
            "created": 0, "model": "fake", "choices": [{
                "index": 0, "delta": delta, "finish_reason": None,
            }],
        },
        {
            "id": f"response-{model}", "object": "chat.completion.chunk",
            "created": 0, "model": "fake", "choices": [{
                "index": 0, "delta": {}, "finish_reason": finish,
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3,
                      "total_tokens": 13},
        },
    ]
    return ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n").encode()


class QuietHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


class GameHandler(QuietHandler):
    requests = []

    def do_GET(self):
        type(self).requests.append((self.path, self.headers.get("X-Agent")))
        if self.path == "/screen":
            payload = json.dumps({
                "ok": True, "width": 320, "height": 200, "frame": 7,
                "image": f"data:image/png;base64,{IMAGE}",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            payload = b"synthetic backend failure"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        type(self).requests.append((self.path, self.headers.get("X-Agent"), body))
        payload = json.dumps({
            "ok": True, "changed": True, "width": 320, "height": 200,
            "frame": 6,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ModelHandler(QuietHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        type(self).requests.append(request)
        turn = len(type(self).requests)
        if turn == 1:
            payload = sse_chunk("press", tool="game_press", tool_args={"key": "enter"})
        elif turn == 2:
            payload = sse_chunk("saves", tool="game_saves")
        else:
            payload = sse_chunk("done", text="adapter ok")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class PiAdapterEndToEndTest(unittest.TestCase):
    def test_pi_executes_game_tool_images_and_survives_http_errors(self):
        GameHandler.requests = []
        ModelHandler.requests = []
        game = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GameHandler)
        model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        threads = []
        for server in (game, model):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                config_dir = pathlib.Path(tmp)
                shutil.copy(ROOT / "pi-agent/SYSTEM.md", config_dir / "SYSTEM.md")
                shutil.copytree(ROOT / "pi-agent/extensions", config_dir / "extensions")
                env = os.environ.copy()
                env.update({
                    "PI_CODING_AGENT_DIR": str(config_dir),
                    "PI_OFFLINE": "1",
                    "QUNXIA_API": f"http://127.0.0.1:{game.server_port}/",
                    "QUNXIA_AGENT": "pi e2e!",
                    "QUNXIA_SCALE": "not-a-number",
                    "QUNXIA_LLM_BASE_URL": f"http://127.0.0.1:{model.server_port}/v1/",
                    "QUNXIA_LLM_MODEL": "fake",
                    "QUNXIA_LLM_API_KEY": "dummy",
                })
                subprocess.run(
                    ["node", str(ROOT / "Scripts/write-pi-model.mjs"),
                     str(config_dir / "models.json")],
                    cwd=ROOT, env=env, check=True, timeout=10,
                )
                process = subprocess.Popen(
                    ["pi", "--mode", "rpc", "--no-session", "--provider", "qunxia",
                     "--model", "fake", "--no-builtin-tools", "--tools",
                     "game_press,game_saves", "--no-skills", "--no-context-files"],
                    cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, bufsize=1,
                )
                process.stdin.write(json.dumps({
                    "id": "prompt-1", "type": "prompt", "message": "test adapters",
                }) + "\n")
                process.stdin.flush()

                events = []
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.time() + 30
                while time.time() < deadline:
                    if not selector.select(timeout=0.5):
                        if process.poll() is not None:
                            break
                        continue
                    line = process.stdout.readline()
                    if not line:
                        break
                    event = json.loads(line)
                    events.append(event)
                    if event.get("type") == "agent_end":
                        break
                else:
                    self.fail("Pi adapter test timed out")

                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                stderr = process.stderr.read()
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
                self.assertEqual(stderr, "")

            self.assertEqual(len(ModelHandler.requests), 3)
            tool_names = {
                tool["function"]["name"]
                for tool in ModelHandler.requests[0].get("tools", [])
            }
            self.assertEqual(tool_names, {"game_press", "game_saves"})
            serialized = json.dumps(ModelHandler.requests[1])
            self.assertIn(f"data:image/png;base64,{IMAGE}", serialized)
            self.assertTrue(GameHandler.requests[0][0].startswith("/key?"))
            self.assertEqual(GameHandler.requests[0][1], "pie2e")
            self.assertEqual(GameHandler.requests[1], ("/screen", "pie2e"))

            tool_ends = [event for event in events
                         if event.get("type") == "tool_execution_end"]
            self.assertEqual(len(tool_ends), 2)
            self.assertFalse(tool_ends[0]["isError"])
            self.assertIn("not atomic", json.dumps(tool_ends[0]))
            self.assertTrue(tool_ends[1]["isError"], tool_ends[1])
            self.assertIn("non-JSON", json.dumps(tool_ends[1]))
            self.assertTrue(any(event.get("type") == "agent_end" for event in events))
            self.assertFalse(any(event.get("type") == "extension_error" for event in events))
        finally:
            for server in (game, model):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
