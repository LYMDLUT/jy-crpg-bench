import http.server
import json
import os
import pathlib
import sys
import threading
import unittest

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


HERE = pathlib.Path(__file__).resolve().parent


class RejectHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": False, "error": "synthetic rejection"}).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class MCPProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_initializes_and_lists_game_tools(self):
        env = os.environ.copy()
        env.update({"QUNXIA_API": "http://127.0.0.1:1", "QUNXIA_AGENT": "test"})
        parameters = StdioServerParameters(
            command=sys.executable, args=[str(HERE / "server.py")], env=env,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                result = await session.list_tools()

        server_info = (initialized.serverInfo if hasattr(initialized, "serverInfo")
                       else initialized.server_info)
        self.assertEqual(server_info.name, "qunxia")
        self.assertEqual(
            {tool.name for tool in result.tools},
            {"look", "guide", "press", "press_sequence", "move", "interact",
             "open_menu", "wait", "save_state", "load_state", "list_states",
             "reset_game"},
        )

    async def test_backend_rejection_is_an_mcp_tool_error(self):
        backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RejectHandler)
        thread = threading.Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env["QUNXIA_API"] = f"http://127.0.0.1:{backend.server_port}"
            parameters = StdioServerParameters(
                command=sys.executable, args=[str(HERE / "server.py")], env=env,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("look", {})
            dumped = result.model_dump(by_alias=True)
            self.assertTrue(dumped["isError"])
            self.assertIn("synthetic rejection", json.dumps(dumped))
        finally:
            backend.shutdown()
            backend.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
