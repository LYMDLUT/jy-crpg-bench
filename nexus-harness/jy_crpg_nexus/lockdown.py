"""The network the agent's container may not have.

Three parts.

``docker_sidecar_lockdown`` closes the container from outside it. Nexus's
Docker provider reaches the runtime through a port Docker publishes, and
Docker publishes nothing for a container on ``--network none`` or on an
``--internal`` network, so the container must keep its bridge. What it must
not keep is a route out. A second, short-lived container joins the agent
container's network namespace (``--network container:<name>``) holding
``NET_ADMIN``, writes an OUTPUT policy of DROP with two exceptions - loopback,
and one TCP destination, the Host's game gateway - and exits. The agent
container was started without ``NET_ADMIN`` (Docker's default), so nothing
inside it, root included, can undo the rules. Replies to connections the Host
opened inbound (the runtime service, the LLM bridge) are ESTABLISHED and pass.

``gongfeng_network_policy`` is the same intent for the Gongfeng provider,
which applies egress rules itself.

``probe`` runs inside the runtime after either and asks whether a public
address answers, whether names resolve, and whether the gateway does answer.
The task aborts the run unless the answers are no, no, yes. The probe is the
verdict; the flags are only how it was tried.
"""
from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass, field
from typing import Any

# Addresses a container must not reach. The catalogue, because one run read
# it; a cloud storage front and a code host, because those answer even when
# nothing else does and so tell a broken lockdown apart from a slow one; a
# bare IP, because it needs no name.
DEFAULT_PROBE_TARGETS = (
    "https://hanxiao.io/jy-crpg-bench/",
    "https://storage.googleapis.com/",
    "https://github.com/",
    "http://1.1.1.1/",
)

PROBE_TIMEOUT_S = 6
DEFAULT_LOCKDOWN_IMAGE = "alpine:3.22"


def docker_cmd() -> str:
    """The docker command Nexus itself uses (``NEXUS_DOCKER_CMD`` may wrap it)."""
    return (os.environ.get("NEXUS_DOCKER_CMD", "docker").strip() or "docker")


def firewall_script(allow: list[tuple[str, int]]) -> str:
    """The shell that the sidecar runs inside the shared namespace.

    Default-deny on OUTPUT, loopback and established replies open, and one
    ACCEPT per (host, port) in ``allow``. IPv6 is closed outright: the gateway
    is reached over IPv4 and a v6 route out would be a second door.
    """
    if not allow:
        raise ValueError("at least one allowed destination is required, or the "
                         "runtime cannot reach the game")
    lines = ["set -e"]
    # The sidecar image may not carry iptables; apk is still reachable at this
    # point because the rules are not in yet.
    lines.append("command -v iptables >/dev/null 2>&1 || apk add -q --no-cache iptables ip6tables >/dev/null")
    # Flush anything an earlier attempt left, then rebuild.
    lines += [
        "iptables -F OUTPUT",
        "iptables -P OUTPUT DROP",
        "iptables -A OUTPUT -o lo -j ACCEPT",
        "iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT "
        "2>/dev/null || iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
    ]
    for host, port in allow:
        lines.append(f"iptables -A OUTPUT -p tcp -d {shlex.quote(host)} --dport {int(port)} -j ACCEPT")
    lines += [
        "if command -v ip6tables >/dev/null 2>&1; then "
        "ip6tables -F OUTPUT 2>/dev/null; ip6tables -P OUTPUT DROP 2>/dev/null; "
        "ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null; "
        "ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true; fi",
        "iptables -S OUTPUT",
    ]
    return "\n".join(lines) + "\n"


def sidecar_command(container: str, allow: list[tuple[str, int]],
                    image: str = DEFAULT_LOCKDOWN_IMAGE) -> list[str]:
    """``docker run`` argv for the firewall sidecar. It joins the agent
    container's network namespace, holds NET_ADMIN for as long as it takes
    to write the rules, and is removed on exit."""
    return [*shlex.split(docker_cmd()), "run", "--rm",
            "--network", f"container:{container}",
            "--cap-add", "NET_ADMIN",
            image, "sh", "-c", firewall_script(allow)]


async def docker_sidecar_lockdown(container: str, allow: list[tuple[str, int]],
                                  image: str = DEFAULT_LOCKDOWN_IMAGE,
                                  timeout_s: float = 180) -> str:
    """Close the container. Returns the rule listing the sidecar printed;
    raises if the sidecar failed, since a half-written policy is no policy."""
    argv = sidecar_command(container, allow, image)
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"firewall sidecar for {container} did not finish in {timeout_s}s")
    if proc.returncode != 0:
        raise RuntimeError(
            f"firewall sidecar for {container} failed ({proc.returncode}): "
            f"{err.decode('utf-8', 'replace').strip() or out.decode('utf-8', 'replace').strip()}")
    return out.decode("utf-8", "replace")


async def find_container(run_id: str | None, runtime_name: str, base_url: str) -> str:
    """The agent container's name. Nexus names it ``nexus-<run_id>-<name>``;
    failing that, the container publishing the runtime's port is the one."""
    docker = shlex.split(docker_cmd())
    candidates = []
    if run_id:
        candidates.append(f"nexus-{run_id}-{runtime_name}")
    candidates.append(f"nexus-user-{runtime_name}")
    for name in candidates:
        proc = await asyncio.create_subprocess_exec(
            *docker, "ps", "--format", "{{.Names}}", "--filter", f"name=^{name}$",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        if name in out.decode().split():
            return name
    port = base_url.rsplit(":", 1)[-1].strip("/")
    if port.isdigit():
        proc = await asyncio.create_subprocess_exec(
            *docker, "ps", "--format", "{{.Names}}", "--filter", f"publish={port}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        names = out.decode().split()
        if len(names) == 1:
            return names[0]
    raise RuntimeError(f"cannot find the runtime container for run {run_id!r} at {base_url}")


async def docker_bridge_gateway() -> str:
    """The address containers on the default bridge reach the Host at."""
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(docker_cmd()), "network", "inspect", "bridge", "--format",
        "{{range .IPAM.Config}}{{.Gateway}}{{end}}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode().strip() or "172.17.0.1"


async def host_address_seen_from(runtime: Any) -> str | None:
    """Docker Desktop gives containers ``host.docker.internal``; a plain
    daemon does not. Ask from inside, while names still resolve."""
    out = await runtime.run_command(
        "getent hosts host.docker.internal 2>/dev/null | awk '{print $1; exit}'", timeout=20)
    addr = (getattr(out, "stdout", "") or "").strip()
    return addr if addr and addr[0].isdigit() and ":" not in addr else None


def gongfeng_network_policy(allow: list[tuple[str, int]]) -> dict[str, Any]:
    """The Gongfeng provider's egress policy with the same shape as the
    firewall: deny by default, allow the gateway."""
    return {"default_action": "deny",
            "egress": [{"action": "allow", "target": f"{host}:{port}"} for host, port in allow]}


def probe_script(targets: tuple[str, ...] | list[str] = DEFAULT_PROBE_TARGETS,
                 gateway_url: str | None = None,
                 timeout_s: int = PROBE_TIMEOUT_S) -> str:
    """A shell script that prints one line per public target, ``REACHED
    <url>`` or ``BLOCKED <url>``; ``RESOLVED`` or ``UNRESOLVED`` for DNS; and,
    if a gateway is named, ``GATEWAY_OK`` or ``GATEWAY_DOWN``. It exits 0
    either way: the lines are the verdict, and a missing curl is a finding."""
    lines = ["set +e"]
    lines.append('if ! command -v curl >/dev/null 2>&1; then echo NOCURL; fi')
    for url in targets:
        q = shlex.quote(url)
        lines.append(
            f"if command -v curl >/dev/null 2>&1 && "
            f"curl -sS -o /dev/null -m {int(timeout_s)} --connect-timeout {int(timeout_s)} {q} "
            f">/dev/null 2>&1; then echo REACHED {q}; else echo BLOCKED {q}; fi")
    # DNS on its own: a policy that drops TCP but answers names still leaks
    # through resolvers that carry data. getent is in every libc.
    lines.append(
        "if command -v getent >/dev/null 2>&1 && getent hosts example.com >/dev/null 2>&1; "
        "then echo RESOLVED; else echo UNRESOLVED; fi")
    if gateway_url:
        q = shlex.quote(gateway_url.rstrip("/") + "/health")
        lines.append(
            f"if command -v curl >/dev/null 2>&1 && "
            f"curl -sS -o /dev/null -m {int(timeout_s)} --connect-timeout {int(timeout_s)} {q} "
            f">/dev/null 2>&1; then echo GATEWAY_OK; else echo GATEWAY_DOWN; fi")
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


@dataclass
class ProbeResult:
    reached: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    dns_resolves: bool | None = None
    gateway_ok: bool | None = None
    curl_missing: bool = False
    raw: str = ""

    @property
    def isolated(self) -> bool:
        """No public target answered and names do not resolve. A missing
        curl is not isolation; it is a probe that could not look. A gateway
        that was asked for and did not answer is a run that cannot play."""
        if self.curl_missing or self.reached or self.dns_resolves is not False:
            return False
        return self.gateway_ok is not False

    def summary(self) -> str:
        if self.isolated:
            s = "isolated: no public address reached, names do not resolve"
            return s + ("; gateway answers" if self.gateway_ok else "")
        parts = []
        if self.reached:
            parts.append("reached " + ", ".join(self.reached))
        if self.dns_resolves:
            parts.append("names resolve")
        if self.dns_resolves is None:
            parts.append("dns not probed")
        if self.gateway_ok is False:
            parts.append("gateway unreachable")
        if self.curl_missing:
            parts.append("curl missing, could not probe")
        return "; ".join(parts) or "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {"isolated": self.isolated, "reached": list(self.reached),
                "blocked": list(self.blocked), "dns_resolves": self.dns_resolves,
                "gateway_ok": self.gateway_ok, "curl_missing": self.curl_missing,
                "summary": self.summary()}


def parse_probe(stdout: str) -> ProbeResult:
    res = ProbeResult(raw=stdout or "")
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "NOCURL":
            res.curl_missing = True
        elif line.startswith("REACHED "):
            res.reached.append(line[len("REACHED "):].strip().strip("'\""))
        elif line.startswith("BLOCKED "):
            res.blocked.append(line[len("BLOCKED "):].strip().strip("'\""))
        elif line == "RESOLVED":
            res.dns_resolves = True
        elif line == "UNRESOLVED":
            res.dns_resolves = False
        elif line == "GATEWAY_OK":
            res.gateway_ok = True
        elif line == "GATEWAY_DOWN":
            res.gateway_ok = False
    return res


async def probe(runtime: Any, *, targets=DEFAULT_PROBE_TARGETS,
                gateway_url: str | None = None,
                timeout_s: int = PROBE_TIMEOUT_S) -> ProbeResult:
    """Run the probe inside ``runtime`` and read its verdict."""
    script = probe_script(targets, gateway_url, timeout_s)
    budget = timeout_s * (len(targets) + 2) + 15
    out = await runtime.run_command(f"sh -c {shlex.quote(script)}", timeout=budget)
    return parse_probe(getattr(out, "stdout", "") or "")
