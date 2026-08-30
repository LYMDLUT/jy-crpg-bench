#!/bin/zsh
# Register the game MCP server with Codex CLI/app. This is intentionally a
# separate setup step: it changes the user's Codex configuration, while merely
# cloning or running the game should not.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

command -v codex >/dev/null || { echo "codex not found" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv not found (install from https://docs.astral.sh/uv/)" >&2; exit 1; }

NAME="${QUNXIA_CODEX_MCP_NAME:-qunxia}"
API="${QUNXIA_API:-http://127.0.0.1:8765}"
API="${API%/}"
AGENT="${QUNXIA_AGENT:-codex}"

if codex mcp get "$NAME" --json >/dev/null 2>&1; then
  if [[ "${QUNXIA_CODEX_REPLACE:-0}" == "1" ]]; then
    codex mcp remove "$NAME"
  else
    echo "Codex MCP server '$NAME' already exists; leaving it unchanged."
    echo "Set QUNXIA_CODEX_REPLACE=1 to replace it with this checkout."
    codex mcp get "$NAME"
    exit 0
  fi
fi

codex mcp add "$NAME" \
  --env "QUNXIA_API=$API" \
  --env "QUNXIA_AGENT=$AGENT" \
  -- uv run --with 'mcp>=1,<3' "$ROOT/mcp-server/server.py"

echo "Registered the '$NAME' game tools for Codex:"
codex mcp get "$NAME"
