import pathlib
import sys
import unittest


BENCH_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

import broker


class PublicSessionRouteTests(unittest.TestCase):
    def test_only_visual_benchmark_routes_are_public(self):
        allowed = {
            ("GET", "api/screen"),
            ("GET", "api/help"),
            ("POST", "api/key"),
            ("POST", "api/keys"),
            ("POST", "api/wait"),
        }
        for method, path in allowed:
            self.assertTrue(broker.public_session_route(method, path))

        for method, path in {
            ("GET", "status"),
            ("GET", "api/history"),
            ("GET", "api/recording"),
            ("POST", "api/reset"),
            ("POST", "api/snapshot"),
            ("GET", ""),
        }:
            self.assertFalse(broker.public_session_route(method, path))

    def test_only_the_spectator_socket_is_public(self):
        self.assertTrue(broker.public_session_route("GET", "ws", websocket=True))
        self.assertFalse(broker.public_session_route("GET", "status", websocket=True))
        self.assertFalse(broker.public_session_route("POST", "ws", websocket=True))


if __name__ == "__main__":
    unittest.main()
