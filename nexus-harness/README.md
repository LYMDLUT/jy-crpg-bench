# jy-crpg-bench under Nexus

A harness for running the benchmark inside Nexus's isolated runtimes with
Claude Code, Codex CLI or DeepSeek Harness (DSH) as the agent, and with the
run bounded by decisions or tokens instead of wall-clock minutes.

This directory holds the integration layer only: a Nexus task, a budgeted
OpenAI client, a network lockdown, a Host-side gateway, and configs. It
imports Nexus at run time and contains none of its source. Nexus is an
internal repository and is not published with this one.

## Why

The public runs were bounded by minutes. Minutes measure the provider's
latency and rate limits as much as the model, and different models make a
different number of decisions in the same four hours. The container the
agent ran in could also reach the public catalogue; one run read earlier
sessions' keypress timelines from it.

Three changes:

**Decision budget.** The game server now takes `QUNXIA_BENCH_ACTIONS`, a
count of decision calls (key submissions and waits). The run ends when it is
spent, whatever the clock says; the clock remains as a ceiling on how long
the machine is held. `POST /session` on the broker accepts `actions`.

**Token budget.** The `budgeted` OpenAI client wraps the real one at Nexus's
LLM bridge on the Host and sums `usage` over the run. Once the budget is
spent, further completions are refused with error code `token_budget_exceeded`;
the harness then closes the run through the operator endpoint `POST /api/end`
with reason `tokens` and files the meter on the run's catalogue entry as its
`usage`. The meter is on the Host; nothing in the container can touch it.

**Closed network.** The container's egress is default-deny with one hole: TCP
to a gateway the task runs on the Host, which forwards the game API
(`/api/help`, `/api/screen`, `/api/keys`, `/api/key`) to the session's play
address and answers everything else 404. The play token never enters the
container. The task then probes from inside - public URLs, DNS, the gateway -
and aborts the run unless nothing public answers, names do not resolve, and
the gateway does. The probe is the verdict; the flags are only how it was tried.

## How the network is closed

Nexus's Docker provider reaches the runtime through a port Docker publishes.
Docker publishes nothing for `--network none` or an `--internal` network, so
the container keeps its bridge and loses its route out instead:

1. The task installs the CLI (pinned version) and uploads the MCP server
   while the network is still open. `latest` is refused: it re-fetches on
   every start, and the network is closed by then.
2. A short-lived sidecar (`alpine`, `--network container:<agent>`,
   `--cap-add NET_ADMIN`) writes `iptables -P OUTPUT DROP` plus ACCEPT for
   loopback, ESTABLISHED/RELATED (replies to the Host's inbound connections)
   and the gateway's `host:port`; IPv6 OUTPUT is dropped outright. It exits.
3. The agent container was started with `--cap-drop NET_ADMIN --cap-drop
   NET_RAW`, so nothing inside it, root included, can undo the rules.
4. The probe runs. `REACHED` anything, `RESOLVED`, `GATEWAY_DOWN` or `NOCURL`
   means the run does not start (`require_isolation: true`).

For the Gongfeng provider, `lockdown.gongfeng_network_policy()` gives the
same intent as the provider's own `network_policy`; set `lockdown_mode:
provider` and the probe still decides.

## Layout

```
nexus-harness/
  README.md
  jy_crpg_nexus/
    __init__.py       imports task and token_budget so `imports: [jy_crpg_nexus]` registers both
    task.py           the `jy_crpg` task: session, gateway, lockdown, probe, agent, close, verdict
    token_budget.py   the `budgeted` OpenAI client and TokenMeter
    lockdown.py       firewall sidecar, Gongfeng policy, probe
    gateway.py        Host-side reverse proxy: the one door to the game
    preinstall.py     installs the CLI at a pinned version before the network closes
    broker_client.py  POST /session, POST /api/end, POST /usage, GET /status
    dsh_cli.py        `look`/`press`/`guide` as a shell command, for DSH (no MCP client)
  configs/
    claude_code.yaml  1000 decisions, Claude Code
    codex.yaml        1000 decisions, Codex CLI
    dsh.yaml          1000 decisions, DSH via cli.py
    token_budget.yaml 2M tokens, Claude Code, `budgeted` client
  tests/
```

## Running

Broker side (unchanged deployment, two new knobs):

```
QUNXIA_RESET_TOKEN=<operator token>   # already required for reset; now also for /api/end
QUNXIA_MAX_ACTIONS=20000              # ceiling on `actions` a session may ask for
```

Host side, from a checkout of Nexus:

```bash
export PYTHONPATH=/path/to/jy-crpg-bench/nexus-harness
export JY_BROKER_URL=http://broker:8080 JY_OPERATOR_TOKEN=...
export JY_MODEL=claude-opus-4.1 JY_API_BASE=https://... JY_API_KEY=...
export JY_AGENT_LABEL=claude-opus-4.1 JY_ACTIONS=1000
uv run nexus run-single -o result.json /path/to/jy-crpg-bench/nexus-harness/configs/claude_code.yaml
```

`result.json` carries the session id, the end reason (`actions`, `tokens`,
`time`, `client_exit`, ...), decisions used, the CLI version, the probe's
verdict, the token meter, the gateway's per-path request counts, and the
agent's exit status and transcript tail. The run's replay and milestones are
on the broker as before.

## What each agent gets

Claude Code and Codex get the game MCP server (`mcp-server/server.py`,
benchmark profile) over stdio, pointed at the gateway. DSH has no MCP client;
it gets the same two tools as `cli.py look` / `cli.py press`, which call the
same API and are counted the same by the server. The prompt says which.

## Tests

```bash
cd /path/to/nexus && PYTHONPATH=/path/to/jy-crpg-bench/nexus-harness \
  uv run python -m unittest discover -s /path/to/jy-crpg-bench/nexus-harness/tests
```

The task tests run against fakes for the broker, runtime and agent. The
contract tests import the installed Nexus and check that the installer
functions, install directories and agent input fields this package depends
on still exist; they skip when Nexus is not importable.

## Not done here

- Per-model repeats and confidence intervals are a matter of running more
  sessions; the harness makes each one comparable, it does not make many.
- The human baseline and the milestone detector's recall are unchanged.
- Codex is run by Nexus with its own sandbox bypassed; the container's
  firewall is the fence, which is why it is checked rather than trusted.
