"""The firewall script, the sidecar command and the probe's verdict."""
import asyncio
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jy_crpg_nexus import lockdown  # noqa: E402


class FirewallScriptTests(unittest.TestCase):
    def test_default_deny_with_one_hole(self):
        s = lockdown.firewall_script([("172.17.0.1", 43210)])
        self.assertIn("iptables -P OUTPUT DROP", s)
        self.assertIn("-o lo -j ACCEPT", s)
        self.assertIn("ESTABLISHED,RELATED", s)
        self.assertIn("-p tcp -d 172.17.0.1 --dport 43210 -j ACCEPT", s)
        self.assertIn("ip6tables -P OUTPUT DROP", s)
        # the sidecar prints the rules it wrote, so the run's log carries them
        self.assertTrue(s.rstrip().endswith("iptables -S OUTPUT"))

    def test_needs_a_destination(self):
        with self.assertRaises(ValueError):
            lockdown.firewall_script([])

    def test_sidecar_joins_the_namespace_without_leaving_net_admin_behind(self):
        argv = lockdown.sidecar_command("nexus-run1-main", [("10.0.0.1", 80)])
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])
        self.assertIn("container:nexus-run1-main", argv)
        self.assertIn("NET_ADMIN", argv)
        self.assertEqual(argv[-3:-1], ["sh", "-c"])
        self.assertIn("--dport 80", argv[-1])

    def test_gongfeng_policy_mirrors_it(self):
        p = lockdown.gongfeng_network_policy([("10.0.0.1", 80)])
        self.assertEqual(p["default_action"], "deny")
        self.assertEqual(p["egress"], [{"action": "allow", "target": "10.0.0.1:80"}])


class ProbeParseTests(unittest.TestCase):
    def test_isolated(self):
        out = ("BLOCKED https://hanxiao.io/jy-crpg-bench/\nBLOCKED https://github.com/\n"
               "UNRESOLVED\nGATEWAY_OK\n")
        r = lockdown.parse_probe(out)
        self.assertTrue(r.isolated)
        self.assertEqual(len(r.blocked), 2)
        self.assertFalse(r.dns_resolves)
        self.assertTrue(r.gateway_ok)
        self.assertIn("gateway answers", r.summary())

    def test_one_reached_is_not_isolated(self):
        r = lockdown.parse_probe("BLOCKED https://github.com/\nREACHED http://1.1.1.1/\nUNRESOLVED\n")
        self.assertFalse(r.isolated)
        self.assertEqual(r.reached, ["http://1.1.1.1/"])
        self.assertIn("reached http://1.1.1.1/", r.summary())

    def test_dns_alone_is_a_leak(self):
        r = lockdown.parse_probe("BLOCKED https://github.com/\nRESOLVED\n")
        self.assertFalse(r.isolated)
        self.assertIn("names resolve", r.summary())

    def test_missing_curl_is_not_isolation(self):
        r = lockdown.parse_probe("NOCURL\nBLOCKED https://github.com/\nUNRESOLVED\n")
        self.assertFalse(r.isolated)
        self.assertTrue(r.curl_missing)

    def test_gateway_down_is_not_a_run(self):
        r = lockdown.parse_probe("BLOCKED https://github.com/\nUNRESOLVED\nGATEWAY_DOWN\n")
        self.assertFalse(r.isolated)
        self.assertIn("gateway unreachable", r.summary())

    def test_no_dns_line_is_unknown_not_isolated(self):
        r = lockdown.parse_probe("BLOCKED https://github.com/\n")
        self.assertFalse(r.isolated)

    def test_to_dict_round_trips_the_verdict(self):
        d = lockdown.parse_probe("BLOCKED x\nUNRESOLVED\n").to_dict()
        self.assertTrue(d["isolated"])
        self.assertEqual(d["blocked"], ["x"])
        self.assertIsNone(d["gateway_ok"])


class ProbeScriptTests(unittest.TestCase):
    def test_script_names_every_target_and_the_gateway(self):
        s = lockdown.probe_script(("https://a/", "http://b/"), "http://172.17.0.1:5000")
        for word in ("REACHED", "BLOCKED", "RESOLVED", "UNRESOLVED", "NOCURL",
                     "GATEWAY_OK", "GATEWAY_DOWN", "https://a/", "http://b/",
                     "http://172.17.0.1:5000/health"):
            self.assertIn(word, s)
        self.assertTrue(s.rstrip().endswith("exit 0"))

    def test_probe_runs_the_script_in_the_runtime(self):
        seen = {}

        class RT:
            async def run_command(self, command, timeout=None, **kw):
                seen["command"] = command
                seen["timeout"] = timeout
                return SimpleNamespace(stdout="BLOCKED https://a/\nUNRESOLVED\nGATEWAY_OK\n", return_code=0)

        r = asyncio.run(lockdown.probe(RT(), targets=("https://a/",), gateway_url="http://h:1"))
        self.assertTrue(r.isolated)
        self.assertTrue(seen["command"].startswith("sh -c "))
        self.assertGreater(seen["timeout"], lockdown.PROBE_TIMEOUT_S * 2)


if __name__ == "__main__":
    unittest.main()
