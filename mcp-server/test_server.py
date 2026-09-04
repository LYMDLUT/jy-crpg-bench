import importlib.util
import pathlib
import unittest
from unittest.mock import patch


MODULE_PATH = pathlib.Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("qunxia_mcp_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


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
        with (
            patch.object(SERVER, "BENCHMARK", True),
            patch.object(SERVER, "_call", return_value={"ok": True}) as call,
        ):
            SERVER._act("/key", {"key": "esc"})
        path = call.call_args.args[1]
        self.assertIn("image=0", path)


if __name__ == "__main__":
    unittest.main()
