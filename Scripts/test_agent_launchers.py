import http.server
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent


class HealthHandler(http.server.BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        type(self).requests.append((self.path, self.headers.get("X-Agent")))
        if self.path == "/help":
            body = b"QunXia test API"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, _format, *_args):
        pass


def executable(path, source):
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


class PiLauncherTest(unittest.TestCase):
    def setUp(self):
        HealthHandler.requests = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_existing_game_is_detected_and_key_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            executable(
                bin_dir / "pi",
                """#!/usr/bin/env node
console.log(JSON.stringify({args: process.argv.slice(2), api: process.env.QUNXIA_API,
                            agent: process.env.QUNXIA_AGENT}));
""",
            )
            config_dir = tmp_path / "pi-config"
            config_dir.mkdir()
            (config_dir / "SYSTEM.md").write_text("game", encoding="utf-8")
            extension_dir = config_dir / "extensions" / "qunxia"
            extension_dir.mkdir(parents=True)
            (extension_dir / "index.ts").write_text("export default () => {};\n",
                                                     encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                "QUNXIA_API": f"http://127.0.0.1:{self.server.server_port}/",
                "QUNXIA_AUTO_START": "0",
                "QUNXIA_PI_DIR": str(config_dir),
                "QUNXIA_LLM_BASE_URL": "http://127.0.0.1:9999/v1/",
                "QUNXIA_LLM_API_KEY": "secret-must-not-be-written",
                "QUNXIA_LLM_MODEL": 'model"with-quote',
            })
            run = subprocess.run(
                ["zsh", str(ROOT / "Scripts/play-agent.sh"), "--no-session"],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            launched = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertEqual(launched["api"], f"http://127.0.0.1:{self.server.server_port}")
            self.assertEqual(launched["agent"], "pi")
            self.assertIn("--no-builtin-tools", launched["args"])
            self.assertIn("--no-session", launched["args"])

            config_text = (config_dir / "models.json").read_text(encoding="utf-8")
            config = json.loads(config_text)
            provider = config["providers"]["qunxia"]
            self.assertEqual(provider["apiKey"], "$QUNXIA_LLM_API_KEY")
            self.assertNotIn("secret-must-not-be-written", config_text)
            self.assertEqual(provider["models"][0]["id"], 'model"with-quote')
            self.assertEqual(HealthHandler.requests, [("/help", "pi")])


class CodexLauncherTest(unittest.TestCase):
    def test_registration_is_absolute_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            marker = tmp_path / "registered"
            calls = tmp_path / "calls.jsonl"
            executable(
                bin_dir / "codex",
                f"""#!/usr/bin/env python3
import json, pathlib, sys
marker = pathlib.Path({str(marker)!r})
calls = pathlib.Path({str(calls)!r})
with calls.open("a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["mcp", "get"] and not marker.exists():
    raise SystemExit(1)
if sys.argv[1:3] == ["mcp", "add"]:
    marker.write_text("yes", encoding="utf-8")
print("ok")
""",
            )
            executable(bin_dir / "uv", "#!/bin/sh\nexit 0\n")
            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                "QUNXIA_API": "http://127.0.0.1:9999/api/",
                "QUNXIA_CODEX_MCP_NAME": "qunxia-test",
            })
            command = ["zsh", str(ROOT / "Scripts/setup-codex.sh")]
            first = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                   capture_output=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                    capture_output=True, timeout=15)
            self.assertEqual(second.returncode, 0, second.stderr)

            recorded = [json.loads(line) for line in calls.read_text().splitlines()]
            adds = [args for args in recorded if args[:2] == ["mcp", "add"]]
            self.assertEqual(len(adds), 1)
            add = adds[0]
            self.assertIn("QUNXIA_API=http://127.0.0.1:9999/api", add)
            self.assertIn("QUNXIA_AGENT=codex", add)
            self.assertIn("mcp>=1,<3", add)
            self.assertIn(str((ROOT / "mcp-server/server.py").resolve()), add)


if __name__ == "__main__":
    unittest.main()
