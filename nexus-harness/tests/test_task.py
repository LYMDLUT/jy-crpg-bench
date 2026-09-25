"""The task's wiring, run against fakes for the broker, runtime and agent.

The real thing needs Docker, a broker and a model. What is checked here is
the order and the decisions: the CLI is installed before the session opens,
the MCP spec carries the gateway address and not the token, a run that is not
isolated is aborted and closed, a spent meter closes the run as `tokens`, an
agent that quit early closes it as `client_exit`, and the installer contract
this package leans on still exists in the installed Nexus.
"""
import asyncio
import importlib
import inspect
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import jy_crpg_nexus  # noqa: E402,F401
from jy_crpg_nexus import lockdown, preinstall, task  # noqa: E402
from jy_crpg_nexus.broker_client import BrokerClient, Session  # noqa: E402
from jy_crpg_nexus.token_budget import TokenMeter  # noqa: E402


# ----------------------------------------------------------------- fakes

async def _noop(**kw):
    return None


class FakeRuntime:
    base_url = "http://172.17.0.1:32768"

    def __init__(self):
        self.commands = []
        self.uploads = []
        self.invoked = []

    async def run_command(self, command, timeout=None, **kw):
        self.commands.append(command)
        if "import mcp" in command:
            return SimpleNamespace(stdout="/nix/runtime/nexus/.venv-3.12/bin/python\n", return_code=0)
        if "host.docker.internal" in command:
            return SimpleNamespace(stdout="", return_code=0)
        return SimpleNamespace(stdout="", return_code=0)

    async def upload_file(self, files, **kw):
        self.uploads.extend(f.path for f in files)

    async def invoke(self, target, **kw):
        self.invoked.append((target, kw))
        return "/tmp/nexus/agents/x/bin/x"


class FakeBroker(BrokerClient):
    def __init__(self, *, over_after_agent=True, live=None):
        super().__init__("http://broker", "optoken")
        self.calls = []
        self.over_after_agent = over_after_agent
        self.live = live or {"session": {"actions": 3, "reason": None}}
        self._agent_ran = False

    async def new_session(self, agent, *, minutes, actions=0, publish=False):
        self.calls.append(("new", agent, minutes, actions, publish))
        return Session(id="sid1", agent=agent, base_url="http://broker/s/sid1/t/TOK",
                       help_url="http://broker/s/sid1/t/TOK/api/help", seconds=minutes * 60,
                       actions_budget=actions or None, ends_at=0.0, raw={})

    async def end_session(self, session, reason, detail=""):
        self.calls.append(("end", reason, detail))
        return {"status": 200, "body": {"ok": True, "reason": reason}}

    async def report_usage(self, session, usage):
        self.calls.append(("usage", usage))
        return {"status": 200, "body": {"ok": True}}

    async def state(self, session):
        if self._agent_ran and self.over_after_agent:
            return 410, {"ok": True, "ended": True, "reason": "actions", "actions": 1000}
        return 200, self.live


class FakeCtx:
    def __init__(self, runtime, client):
        self.runtime = runtime
        self.openai_client = client
        self.run_id = "run1"

    async def get_runtime(self, name="main", **kw):
        return self.runtime


def _input(run_agent, **over):
    kw = dict(agent_label="test-model", broker_url="http://broker", operator_token="optoken",
              actions=1000, minutes=30, cli="claude_code", cli_version="2.1.153",
              lockdown_mode="none", gateway_host="172.17.0.1")
    kw.update(over)
    return task.JyCrpgInput(run_agent=run_agent, **kw)


def _run(inp, broker, runtime, client=None, probe_out="BLOCKED x\nUNRESOLVED\nGATEWAY_OK\n"):
    async def fake_probe(rt, *, targets, gateway_url, timeout_s=6):
        return lockdown.parse_probe(probe_out)

    class FakeGateway:
        def __init__(self, upstream, host="0.0.0.0", port=0):
            self.upstream, self.port = upstream, 45678
        async def start(self): pass
        async def stop(self): pass
        def stats(self): return {"port": self.port, "requests": {}, "refused": {}, "upstream_errors": 0}

    with mock.patch.object(task, "require_context", return_value=FakeCtx(runtime, client)), \
         mock.patch.object(task, "END_WAIT_S", 0.2), mock.patch.object(task, "END_POLL_S", 0.05), \
         mock.patch.object(task, "GameGateway", FakeGateway), \
         mock.patch.object(lockdown, "probe", fake_probe), \
         mock.patch.object(task, "BrokerClient", lambda *a, **k: broker):
        return asyncio.run(task.jy_crpg(inp))


# ----------------------------------------------------------------- tests

class WiringTests(unittest.TestCase):
    def test_mcp_spec_points_at_the_gateway_not_the_token(self):
        spec = task.mcp_server_spec("http://172.17.0.1:45678", "m", "/py")
        self.assertEqual(spec["name"], "qunxia")
        self.assertEqual(spec["command"], "/py")
        self.assertEqual(spec["env"]["QUNXIA_API"], "http://172.17.0.1:45678/api")
        self.assertEqual(spec["env"]["QUNXIA_MCP_PROFILE"], "benchmark")
        self.assertNotIn("TOK", json.dumps(spec))

    def test_agent_kwargs_per_cli(self):
        base = dict(run_agent=_noop, agent_label="m", cli_version="1")
        cc = task.agent_kwargs(task.JyCrpgInput(cli="claude_code", **base), "http://g:1", 60, "1", "/py")
        self.assertEqual(cc["mcp_servers_mode"], "strict_file")
        self.assertEqual(cc["version"], "1")
        self.assertEqual(cc["mcp_servers"][0]["command"], "/py")
        cx = task.agent_kwargs(task.JyCrpgInput(cli="codex", **base), "http://g:1", 60, "1", "/py")
        self.assertIn("mcp_servers", cx)
        self.assertNotIn("mcp_servers_mode", cx)
        dsh = task.agent_kwargs(task.JyCrpgInput(cli="dsh", **base), "http://g:1", 60, "1", "/py")
        self.assertNotIn("mcp_servers", dsh)
        self.assertIn("/py /opt/jy-crpg/mcp-server/cli.py look", dsh["user_prompt"])
        self.assertEqual(dsh["extra_env"]["QUNXIA_API"], "http://g:1/api")

    def test_mcp_files_are_the_three_in_the_repo(self):
        names = sorted(pathlib.Path(f["path"]).name for f in task.mcp_files())
        self.assertEqual(names, ["ADAPTER.md", "game_knowledge.py", "server.py"])

    def test_summarize_final_reads_both_shapes(self):
        self.assertEqual(task.summarize_final({"ended": True, "reason": "actions", "actions": 9}),
                         ("actions", 9))
        self.assertEqual(task.summarize_final({"session": {"reason": "time", "decision_calls": 4}}),
                         ("time", 4))
        self.assertEqual(task.summarize_final(None), (None, None))

    def test_classify_end(self):
        m = TokenMeter(10); m.add({"total_tokens": 10})
        self.assertEqual(task.classify_end(SimpleNamespace(exit_code=0), m)[0], "tokens")
        self.assertEqual(task.classify_end(SimpleNamespace(exit_code=1), None),
                         ("client_exit", "agent exited with code 1"))


class FlowTests(unittest.TestCase):
    def _agent(self, broker, exit_code=0):
        async def run_agent(**kw):
            broker._agent_ran = True
            self.agent_kwargs = kw
            return SimpleNamespace(success=exit_code == 0, output="played", stderr="",
                                   exit_code=exit_code, execution_time=1.0,
                                   failure_kind=None, failure_stage=None)
        return run_agent

    def test_happy_path_order_and_verdict(self):
        broker, rt = FakeBroker(), FakeRuntime()
        out = _run(_input(self._agent(broker)), broker, rt)
        self.assertTrue(out.ok)
        self.assertEqual(out.reason, "actions")
        self.assertEqual(out.actions_used, 1000)
        self.assertEqual(out.actions_budget, 1000)
        self.assertEqual(out.cli_version, "2.1.153")
        # installed and uploaded before the session was opened
        self.assertEqual(rt.invoked[0][0], preinstall.INSTALLERS["claude_code"])
        self.assertEqual(rt.invoked[0][1]["install_dir"], preinstall.install_dir("claude_code"))
        self.assertEqual(rt.invoked[0][1]["version"], "2.1.153")
        self.assertIn("/opt/jy-crpg/mcp-server/server.py", rt.uploads)
        self.assertEqual(broker.calls[0][:4], ("new", "test-model", 30, 1000))
        # the server ended the run itself: no end call, no usage without a meter
        self.assertEqual([c[0] for c in broker.calls], ["new"])
        self.assertIsNone(out.end_call)
        self.assertEqual(self.agent_kwargs["mcp_servers"][0]["env"]["QUNXIA_API"],
                         "http://172.17.0.1:45678/api")
        self.assertEqual(out.gateway["port"], 45678)

    def test_not_isolated_aborts_before_the_agent(self):
        broker, rt = FakeBroker(), FakeRuntime()
        ran = []
        async def run_agent(**kw):
            ran.append(1)
        out = _run(_input(run_agent), broker, rt, probe_out="REACHED https://github.com/\nRESOLVED\n")
        self.assertFalse(out.ok)
        self.assertIn("not isolated", out.aborted)
        self.assertEqual(ran, [])
        self.assertEqual(broker.calls[-1][0], "end")
        self.assertEqual(broker.calls[-1][1], "client_exit")
        self.assertFalse(out.probe["isolated"])

    def test_not_isolated_continues_when_told_to(self):
        broker, rt = FakeBroker(), FakeRuntime()
        out = _run(_input(self._agent(broker), require_isolation=False), broker, rt,
                   probe_out="REACHED https://github.com/\nRESOLVED\n")
        self.assertTrue(out.ok)
        self.assertIsNone(out.aborted)
        self.assertFalse(out.probe["isolated"])

    def test_agent_quits_early_closes_as_client_exit(self):
        broker, rt = FakeBroker(over_after_agent=False), FakeRuntime()
        out = _run(_input(self._agent(broker, exit_code=2)), broker, rt)
        ends = [c for c in broker.calls if c[0] == "end"]
        self.assertEqual(ends, [("end", "client_exit", "agent exited with code 2")])
        self.assertFalse(out.ok)            # never saw the 410 within the (patched) wait
        self.assertEqual(out.agent["exit_code"], 2)

    def test_spent_meter_closes_as_tokens_and_files_usage(self):
        broker, rt = FakeBroker(over_after_agent=False), FakeRuntime()
        client = SimpleNamespace(meter=TokenMeter(100))
        client.meter.add({"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110})
        with mock.patch.object(task, "meter_of", lambda c: c.meter):
            out = _run(_input(self._agent(broker)), broker, rt, client=client)
        kinds = [c[0] for c in broker.calls]
        self.assertEqual(kinds, ["new", "end", "usage"])
        self.assertEqual(broker.calls[1][1], "tokens")
        self.assertEqual(broker.calls[2][1]["totalTokens"], 110)
        self.assertTrue(out.tokens["spent"])

    def test_agent_exception_is_recorded_not_raised(self):
        broker, rt = FakeBroker(), FakeRuntime()
        async def run_agent(**kw):
            broker._agent_ran = True
            raise RuntimeError("boom")
        out = _run(_input(run_agent), broker, rt)
        self.assertFalse(out.agent["ran"])
        self.assertIn("boom", out.agent["error"])

    def test_latest_is_refused(self):
        broker, rt = FakeBroker(), FakeRuntime()
        with self.assertRaises(ValueError):
            _run(_input(self._agent(broker), cli_version="latest"), broker, rt)
        self.assertEqual(broker.calls, [])   # nothing opened


class NexusContractTests(unittest.TestCase):
    """The installers this package invokes by import path exist and take
    what preinstall passes. Skipped when Nexus is not importable."""

    def _check(self, cli, extra=None):
        mod_path, func = preinstall.INSTALLERS[cli].split("::")
        try:
            mod = importlib.import_module(mod_path)
        except ImportError as exc:
            self.skipTest(f"nexus not importable: {exc}")
        fn = getattr(mod, func)
        params = inspect.signature(fn).parameters
        kw = preinstall.installer_kwargs(cli, "1.0.0", npm_registry="http://r", **(extra or {}))
        for k in kw:
            self.assertIn(k, params, f"{preinstall.INSTALLERS[cli]} lacks {k}")

    def test_claude_code(self): self._check("claude_code")
    def test_codex(self): self._check("codex")
    def test_dsh(self): self._check("dsh", {"acp_version": "1.0.0"})

    def test_install_dirs_match_nexus_defaults(self):
        try:
            from nexus.extensions.agents.claude_code import runtime_setup as cc
            from nexus.extensions.agents.codex import runtime_setup as cx
            from nexus.extensions.agents.dsh import installer as dsh
        except ImportError as exc:
            self.skipTest(f"nexus not importable: {exc}")
        self.assertEqual(preinstall.install_dir("claude_code"), cc.DEFAULT_INSTALL_DIR)
        self.assertEqual(preinstall.install_dir("codex"), cx.DEFAULT_INSTALL_DIR)
        self.assertEqual(preinstall.install_dir("dsh"), dsh.DEFAULT_INSTALL_DIR)

    def test_agent_inputs_accept_what_the_task_sends(self):
        try:
            from nexus.extensions.agents.claude_code.agent import ClaudeCodeInput
            from nexus.extensions.agents.codex.agent import CodexInput
            from nexus.extensions.agents.dsh.agent import DshInput
        except ImportError as exc:
            self.skipTest(f"nexus not importable: {exc}")
        base = dict(run_agent=_noop, agent_label="m", cli_version="1")
        for cli, model in (("claude_code", ClaudeCodeInput), ("codex", CodexInput), ("dsh", DshInput)):
            kw = task.agent_kwargs(task.JyCrpgInput(cli=cli, **base), "http://g:1", 60, "1", "/py")
            unknown = set(kw) - set(model.model_fields)
            self.assertEqual(unknown, set(), f"{cli}: {unknown}")


if __name__ == "__main__":
    unittest.main()
