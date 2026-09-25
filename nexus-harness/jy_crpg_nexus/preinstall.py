"""Install the CLI before the network closes.

Nexus's installed agents fetch their CLI from npm at the start of every run.
Once the container's egress is closed that fetch fails, so the harness runs
the same installer first, with the same pinned version, while the network is
still open. The agent's own install step then finds the version in place and
skips the fetch - for a pinned version; ``latest`` always re-fetches, so the
task refuses it.

The installers are Nexus's own, called through ``runtime.invoke`` by import
path; nothing of them is copied here. Their signatures are the contract this
file depends on, and ``test_preinstall`` checks it against the installed
Nexus.
"""
from __future__ import annotations

from typing import Any, Literal

Cli = Literal["claude_code", "codex", "dsh"]

# Where each agent installs by default. The path is whatever the installed
# Nexus computes on the Host (it is passed into the container as a string),
# so it is read from Nexus rather than restated; a restated path that drifted
# would be a silent re-fetch at run time. The fallbacks are for a Host with
# no Nexus, i.e. tests of this module alone.
_FALLBACK_INSTALL_DIRS = {
    "claude_code": "/tmp/nexus/agents/claude-code",
    "codex": "/tmp/nexus/agents/codex-cli",
    "dsh": "/tmp/nexus/agents/dsh",
}

_INSTALL_DIR_SOURCES = {
    "claude_code": "nexus.extensions.agents.claude_code.runtime_setup",
    "codex": "nexus.extensions.agents.codex.runtime_setup",
    "dsh": "nexus.extensions.agents.dsh.installer",
}


def install_dir(cli: Cli) -> str:
    try:
        import importlib
        return str(importlib.import_module(_INSTALL_DIR_SOURCES[cli]).DEFAULT_INSTALL_DIR)
    except Exception:
        return _FALLBACK_INSTALL_DIRS[cli]

INSTALLERS = {
    "claude_code": "nexus.extensions.agents.claude_code.installer::install_claude_code_via_npm",
    "codex": "nexus.extensions.agents.codex.installer::install_codex_cli",
    "dsh": "nexus.extensions.agents.dsh.installer::install_dsh",
}


def installer_kwargs(cli: Cli, version: str, *, npm_registry: str | None,
                     acp_version: str | None = None) -> dict[str, Any]:
    if not version or version == "latest":
        raise ValueError(
            f"{cli} needs a pinned version: 'latest' is re-fetched on every start, "
            "and the network is closed by then")
    kw: dict[str, Any] = {"install_dir": install_dir(cli), "version": version}
    if npm_registry:
        kw["npm_registry"] = npm_registry
    if cli == "dsh" and acp_version:
        kw["acp_version"] = acp_version
    return kw


async def preinstall(runtime: Any, cli: Cli, version: str, *, npm_registry: str | None = None,
                     acp_version: str | None = None) -> str:
    """Run the agent's installer now. Returns the path it reports."""
    kw = installer_kwargs(cli, version, npm_registry=npm_registry, acp_version=acp_version)
    path = await runtime.invoke(INSTALLERS[cli], **kw)
    return str(path)
