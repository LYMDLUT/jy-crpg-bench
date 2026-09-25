"""The Nexus harness for jy-crpg-bench.

Importing this package registers with Nexus:

- the ``jy_crpg`` task, which takes a session from the broker, starts the game
  MCP server on the Host, proxies it into a locked-down runtime, runs the
  configured CLI agent (Claude Code, Codex, DeepSeek Harness) against it, and
  returns the game server's own verdict;
- the ``budgeted`` OpenAI client, which wraps another client and refuses
  completions once a token budget is spent.

Only Nexus's public registries are imported here; nothing of Nexus is vendored.
"""
from . import task as _task  # noqa: F401  registers jy_crpg
from . import token_budget as _token_budget  # noqa: F401  registers budgeted

__all__ = ["task", "token_budget", "lockdown", "broker_client"]
