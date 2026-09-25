"""The ``jy_crpg`` task: one benchmark run of 金庸群俠傳 under Nexus.

The order of things, and why each is where it is:

1. Acquire the runtime container. While its network is still open, install
   the CLI at a pinned version and upload the game MCP server; nothing is
   fetched after this point.
2. Open a session at the broker (Host side). The broker starts a game server
   and hands back a play address with the session token in its path and, when
   asked, a decision budget the server itself enforces. Start the gateway: a
   small reverse proxy on the Host that forwards the game API to that play
   address and nothing else, so the token never enters the container and the
   broker's other routes are not reachable from it even in principle.
3. Close the container's network: default-deny egress with one hole, TCP to
   the gateway. Then probe from inside. If a public address answers, or names
   resolve, or the gateway does not answer, the run is aborted before the
   agent starts. A flag that was passed is not a network that is closed.
4. Run the CLI agent (Claude Code, Codex; DSH has no MCP client, so it gets
   the same two tools as a shell command) with the MCP server as its only way
   to the game. The model is reached through Nexus's LLM bridge, which is the
   Host's client - the ``budgeted`` one, if the config sets a token budget.
5. When the agent exits: if the token meter is spent, close the run as
   ``tokens``; if the agent quit while the run was still open, close it as
   ``client_exit``. File the token meter on the run's catalogue entry. Read
   the run's final numbers back from the broker and return them.

Nothing here reads Nexus internals beyond ``require_context``, the runtime's
``run_command``/``upload_file``/``invoke``, and the two registries.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any, Literal

from nexus.core import require_context
from nexus.core.task import TaskRunInput, TaskRunOutput, WithAgentRunner, task_registry

from . import lockdown, preinstall
from .broker_client import BrokerClient, BrokerError, Session
from .gateway import GameGateway
from .token_budget import meter_of

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SOURCE_DIR = REPO_ROOT / "mcp-server"
MCP_FILES = ("server.py", "game_knowledge.py", "ADAPTER.md")
RUNTIME_MCP_DIR = "/opt/jy-crpg/mcp-server"

# Pinned CLI versions. A run's record names the CLI build that made it; a
# floating tag would make two runs a week apart two different harnesses.
DEFAULT_CLI_VERSIONS = {"claude_code": "2.1.153", "codex": "0.114.0", "dsh": "0.1.0-rc.6"}

# Where a python that imports ``mcp`` may be. Nexus's runtime venv has it.
PYTHON_CANDIDATES = (
    "/nix/runtime/nexus/.venv-*/bin/python",
    "/nix/runtime/nix-env/bin/python3",
    "python3",
)

# What the agent is told. The brief is the game's own help page, which the MCP
# server sends as its instructions; this only says where the game is.
DEFAULT_PROMPT = (
    "You are playing 金庸群俠傳 (Heroes of Jin Yong, 1996) through the `qunxia` "
    "MCP server. Its instructions describe the game and the two tools, `look` and "
    "`press`. The run is scored by what the character achieves in the game; "
    "there is no file to write and no other system to use. Play until the "
    "server tells you the run has ended, then stop."
)

DSH_PROMPT_SUFFIX = (
    "\n\nThere is no MCP client in this environment. Use the shell: "
    "`{py} {dir}/cli.py look` shows the screen and "
    "`{py} {dir}/cli.py press <key> [<key>...]` presses keys; both print the "
    "same text the MCP tools would and save the screen to /tmp/screen.png, "
    "which you should view after every action. Run `{py} {dir}/cli.py guide` first."
)


class JyCrpgInput(TaskRunInput, WithAgentRunner):
    agent_label: str
    """The name the run is listed under in the catalogue, e.g. ``claude-opus-4.1``."""

    broker_url: str | None = None
    """The broker. Falls back to ``JY_BROKER_URL``."""
    operator_token: str | None = None
    """The broker's operator token, for ``/api/end`` and a run's live numbers.
    Falls back to ``JY_OPERATOR_TOKEN``. Without it the run still ends at its
    own budget; only the harness's early close and the live status are lost."""

    actions: int = 1000
    """Decision budget. 0 means the clock alone, which this harness discourages."""
    minutes: int = 240
    """Ceiling on how long the machine is held."""
    publish: bool = False
    """Whether the broker may put the run on the public catalogue."""

    cli: Literal["claude_code", "codex", "dsh"] = "claude_code"
    """Which CLI the configured agent is. Decides how the MCP server is wired."""
    cli_version: str = ""
    """The CLI's pinned version. Installed before the network closes; the
    agent then finds it in place. ``latest`` is refused. Defaults per CLI."""
    npm_registry: str | None = None
    """Registry for the install, when the agent's default is not reachable."""
    prompt: str = DEFAULT_PROMPT
    working_dir: str = "/workspace"

    lockdown_mode: Literal["docker_sidecar", "provider", "none"] = "docker_sidecar"
    """How the container's egress is closed. ``provider`` means the runtime
    provider did it (Gongfeng ``network_policy``); ``none`` is for debugging.
    The probe runs and aborts in every mode."""
    lockdown_image: str = lockdown.DEFAULT_LOCKDOWN_IMAGE
    require_isolation: bool = True
    """Abort the run unless the probe says isolated. Off only for debugging;
    the output records the probe either way."""
    probe_targets: list[str] = list(lockdown.DEFAULT_PROBE_TARGETS)

    gateway_host: str | None = None
    """The Host address the container reaches the gateway at. Default:
    ``host.docker.internal`` where it resolves, else the Docker bridge gateway."""
    gateway_port: int = 0
    """0 picks a free port."""

    agent_timeout: float | None = None
    """Seconds the agent process may run. Default: ``minutes`` plus ten."""


class JyCrpgOutput(TaskRunOutput):
    ok: bool
    session_id: str | None = None
    agent_label: str
    reason: str | None = None
    """The game server's end reason: actions, time, tokens, client_exit, idle..."""
    aborted: str | None = None
    """Set when the harness refused to run the agent (isolation, broker)."""
    actions_budget: int | None = None
    actions_used: int | None = None
    cli_version: str | None = None
    probe: dict[str, Any] | None = None
    tokens: dict[str, Any] | None = None
    end_call: dict[str, Any] | None = None
    usage_call: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    """The run's own numbers, as the broker reports them at the end."""
    agent: dict[str, Any] | None = None
    """success, exit_code, execution_time, and the tail of the transcript."""
    gateway: dict[str, Any] | None = None
    """Requests the gateway saw, by path, so the record shows the agent used
    the game API and nothing else."""


# ------------------------------------------------------------------ pieces

def _env(name: str, given: str | None) -> str | None:
    return given if given else (os.environ.get(name) or None)


def mcp_files() -> list[dict[str, str]]:
    """The MCP server as upload items: three files, nothing generated."""
    files = []
    for name in MCP_FILES:
        content = (MCP_SOURCE_DIR / name).read_bytes()
        files.append({"path": f"{RUNTIME_MCP_DIR}/{name}",
                      "content": base64.b64encode(content).decode("ascii"),
                      "encoding": "base64"})
    return files


async def upload_mcp(runtime: Any, with_cli: bool = False) -> None:
    from nexus.runtime.executors.models.file import FileItem

    items = [FileItem(**f) for f in mcp_files()]
    if with_cli:
        from .dsh_cli import CLI_SOURCE
        items.append(FileItem(path=f"{RUNTIME_MCP_DIR}/cli.py", content=CLI_SOURCE))
    await runtime.run_command(f"mkdir -p {shlex.quote(RUNTIME_MCP_DIR)}", timeout=30)
    await runtime.upload_file(files=items)


def python_probe_script(candidates=PYTHON_CANDIDATES) -> str:
    parts = []
    for pat in candidates:
        parts.append(
            f'for p in {pat}; do if [ -x "$p" ] || command -v "$p" >/dev/null 2>&1; then '
            f'if "$p" -c "import mcp" >/dev/null 2>&1; then echo "$p"; exit 0; fi; fi; done;')
    return " ".join(parts) + " exit 1"


async def find_mcp_python(runtime: Any) -> str:
    """A python in the container that imports ``mcp``. Checked, not assumed:
    the MCP server is the agent's only door and a wrong interpreter is a run
    with no game."""
    out = await runtime.run_command(f"sh -c {shlex.quote(python_probe_script())}", timeout=120)
    lines = (getattr(out, "stdout", "") or "").strip().splitlines()
    if (getattr(out, "return_code", 1) or 0) != 0 or not lines:
        raise RuntimeError("no python in the runtime can import mcp; the game MCP server needs it")
    return lines[-1].strip()


def mcp_env(game_url: str, agent_label: str) -> dict[str, str]:
    """The environment the MCP server runs with inside the container. The
    game URL is the Host gateway's; the play token is not in it."""
    return {"QUNXIA_API": game_url.rstrip("/") + "/api",
            "QUNXIA_MCP_PROFILE": "benchmark",
            "QUNXIA_AGENT": agent_label,
            "QUNXIA_BENCH_LANG": "en"}


def mcp_server_spec(game_url: str, agent_label: str, python: str) -> dict[str, Any]:
    """The flat stdio spec both Claude Code and Codex accept."""
    return {"name": "qunxia", "command": python,
            "args": [f"{RUNTIME_MCP_DIR}/server.py"],
            "env": mcp_env(game_url, agent_label)}


def agent_kwargs(inp: JyCrpgInput, game_url: str, timeout: float, version: str,
                 python: str) -> dict[str, Any]:
    """Per-CLI wiring. The same MCP server, three ways in."""
    spec = mcp_server_spec(game_url, inp.agent_label, python)
    common: dict[str, Any] = {"user_prompt": inp.prompt, "version": version,
                              "working_dir": inp.working_dir, "timeout": timeout}
    if inp.npm_registry:
        common["npm_registry"] = inp.npm_registry
    if inp.cli == "claude_code":
        return {**common, "mcp_servers": [spec], "mcp_servers_mode": "strict_file",
                "extra_env": {"DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1",
                              "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}}
    if inp.cli == "codex":
        return {**common, "mcp_servers": [spec]}
    # DSH speaks ACP and has no MCP client. It gets a shell and the same two
    # tools as a command; the server counts a press the same either way.
    return {**common,
            "permission_mode": "workspace-write",
            "extra_env": spec["env"],
            "user_prompt": inp.prompt + DSH_PROMPT_SUFFIX.format(py=python, dir=RUNTIME_MCP_DIR)}


def classify_end(agent_out: Any, meter: Any) -> tuple[str, str]:
    """What to tell the game server when the agent stopped before the server
    ended the run."""
    if meter is not None and meter.spent:
        return "tokens", f"{meter.used} of {meter.budget} tokens"
    code = getattr(agent_out, "exit_code", None)
    return "client_exit", f"agent exited with code {code}"


def agent_summary(out: Any, tail: int = 4000) -> dict[str, Any]:
    if out is None:
        return {"ran": False}
    text = getattr(out, "output", "") or ""
    return {"ran": True,
            "success": bool(getattr(out, "success", False)),
            "exit_code": getattr(out, "exit_code", None),
            "execution_time": getattr(out, "execution_time", None),
            "failure_kind": getattr(out, "failure_kind", None),
            "failure_stage": getattr(out, "failure_stage", None),
            "output_tail": text[-tail:],
            "stderr_tail": (getattr(out, "stderr", "") or "")[-tail:]}


def summarize_final(final: dict | None) -> tuple[str | None, int | None]:
    """(reason, actions) from either the broker's 410 body or a live status."""
    if not final:
        return None, None
    summary = final.get("session") if isinstance(final.get("session"), dict) else final
    actions = summary.get("actions", summary.get("decision_calls"))
    return summary.get("reason"), actions


# How long to wait for the broker's 410 after the agent leaves, and how often
# to ask. Module-level so a test can shorten them.
END_WAIT_S = 180.0
END_POLL_S = 5.0


async def wait_for_end(broker: BrokerClient, session: Session, deadline_s: float | None = None,
                       poll_s: float | None = None) -> dict | None:
    """After the agent leaves, give the game server up to three minutes to
    finalize and the broker to publish the run's numbers. Returns the 410
    summary, or the last live status if it never came."""
    deadline_s = END_WAIT_S if deadline_s is None else deadline_s
    poll_s = END_POLL_S if poll_s is None else poll_s
    end = time.time() + deadline_s
    last = None
    while True:
        status, body = await broker.state(session)
        if status == 410 and isinstance(body, dict):
            return dict(body, ended=True)
        if status == 200 and isinstance(body, dict):
            last = body
        if time.time() >= end:
            return last
        await asyncio.sleep(poll_s)


# -------------------------------------------------------------------- task

@task_registry.register("jy_crpg")
async def jy_crpg(inp: JyCrpgInput) -> JyCrpgOutput:
    ctx = require_context()
    broker_url = _env("JY_BROKER_URL", inp.broker_url)
    if not broker_url:
        raise ValueError("broker_url (or JY_BROKER_URL) is required")
    broker = BrokerClient(broker_url, _env("JY_OPERATOR_TOKEN", inp.operator_token))
    meter = meter_of(ctx.openai_client)
    version = inp.cli_version or DEFAULT_CLI_VERSIONS[inp.cli]
    out = JyCrpgOutput(ok=False, agent_label=inp.agent_label, cli_version=version)

    # 1. The runtime, and everything that needs the network, first. A session
    # opened before this would have its clock running for nobody.
    runtime = await ctx.get_runtime()
    await preinstall.preinstall(runtime, inp.cli, version, npm_registry=inp.npm_registry)
    python = await find_mcp_python(runtime)
    await upload_mcp(runtime, with_cli=(inp.cli == "dsh"))
    gateway_host = inp.gateway_host or await lockdown.host_address_seen_from(runtime) \
        or await lockdown.docker_bridge_gateway()

    session: Session | None = None
    gateway: GameGateway | None = None
    try:
        # 2. The session, and the one door to it.
        session = await broker.new_session(inp.agent_label, minutes=inp.minutes,
                                           actions=inp.actions, publish=inp.publish)
        out.session_id = session.id
        out.actions_budget = session.actions_budget
        gateway = GameGateway(upstream=session.base_url, host="0.0.0.0", port=inp.gateway_port)
        await gateway.start()
        game_url = f"http://{gateway_host}:{gateway.port}"

        # 3. Close the network, then check that it is closed.
        if inp.lockdown_mode == "docker_sidecar":
            container = await lockdown.find_container(ctx.run_id, "main", getattr(runtime, "base_url", ""))
            listing = await lockdown.docker_sidecar_lockdown(
                container, [(gateway_host, gateway.port)], inp.lockdown_image)
            logger.info("firewall on %s:\n%s", container, listing)
        probe = await lockdown.probe(runtime, targets=tuple(inp.probe_targets), gateway_url=game_url)
        out.probe = probe.to_dict()
        if not probe.isolated:
            msg = f"runtime is not isolated: {probe.summary()}"
            if inp.require_isolation:
                out.aborted = msg
                out.end_call = await broker.end_session(session, "client_exit", "harness aborted: " + msg)
                return out
            logger.warning("%s (require_isolation is off; continuing)", msg)

        # 4. The agent.
        timeout = inp.agent_timeout or (inp.minutes + 10) * 60.0
        agent_out = None
        try:
            agent_out = await inp.run_agent(**agent_kwargs(inp, game_url, timeout, version, python))
        except Exception as exc:  # the run is still scored; the record says why
            logger.exception("agent failed")
            out.agent = {"ran": False, "error": repr(exc)}
        else:
            out.agent = agent_summary(agent_out)

        # 5. Close the run if the server has not; file the meter; read the verdict.
        over = await broker.ended_payload(session)
        if over is None:
            reason, detail = classify_end(agent_out, meter)
            out.end_call = await broker.end_session(session, reason, detail)
        if meter is not None:
            out.tokens = meter.snapshot()
            out.usage_call = await broker.report_usage(session, meter.report())
        final = over or await wait_for_end(broker, session)
        out.result = final
        out.reason, out.actions_used = summarize_final(final)
        out.ok = bool(final and final.get("ended"))
        return out
    except BrokerError as exc:
        out.aborted = f"broker: {exc}"
        return out
    finally:
        if gateway is not None:
            out.gateway = gateway.stats()
            await gateway.stop()
