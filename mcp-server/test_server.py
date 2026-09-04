import importlib.util
import os
import pathlib
import unittest
import urllib.parse
from unittest.mock import patch


MODULE_PATH = pathlib.Path(__file__).with_name("server.py")
SESSION_GUIDE = "# guide served by the active benchmark session"
SESSION_GUIDE_URL = "data:text/plain," + urllib.parse.quote(SESSION_GUIDE)


def load_server(profile):
    environment = {"QUNXIA_MCP_PROFILE": profile}
    if profile == "benchmark":
        environment["QUNXIA_BENCH_HELP_URL"] = SESSION_GUIDE_URL
    with patch.dict(os.environ, environment):
        spec = importlib.util.spec_from_file_location(
            f"qunxia_mcp_server_{profile}", MODULE_PATH)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        return server


SERVER = load_server("standalone")


class PressContractTests(unittest.TestCase):
    def test_omitted_hold_uses_http_server_default(self):
        with patch.object(SERVER, "_act", return_value=[]) as act:
            SERVER.press("esc")
        act.assert_called_once_with(
            "/key", {"key": "esc"}, note="esc", stable=None,
        )

    def test_explicit_hold_is_forwarded(self):
        with patch.object(SERVER, "_act", return_value=[]) as act:
            SERVER.press("kp3", times=2, hold=14, stable=8)
        act.assert_called_once_with(
            "/keys", {"keys": ["kp3", "kp3"], "hold": 14},
            note="kp3 x2", stable=8,
        )

    def test_benchmark_actions_suppress_images(self):
        benchmark = load_server("benchmark")
        with patch.object(benchmark, "_call", return_value={"ok": True}) as call:
            benchmark._act("/key", {"key": "esc"})
        path = call.call_args.args[1]
        self.assertIn("scale=1", path)
        self.assertIn("image=0", path)

    def test_profiles_register_the_expected_tools(self):
        standalone = set(SERVER.mcp._tool_manager._tools)
        benchmark = load_server("benchmark")
        self.assertEqual(
            standalone,
            {
                "guide", "look", "press", "press_sequence", "move", "wait",
                "save_state", "load_state", "list_states", "reset_game",
            },
        )
        self.assertEqual(
            set(benchmark.mcp._tool_manager._tools),
            {"look", "press", "press_sequence", "wait"},
        )
        self.assertNotIn("interact", standalone)
        self.assertNotIn("open_menu", standalone)

    def test_benchmark_uses_the_connected_session_guide(self):
        benchmark = load_server("benchmark")
        self.assertTrue(benchmark.GUIDE.endswith(SESSION_GUIDE))


if __name__ == "__main__":
    unittest.main()
