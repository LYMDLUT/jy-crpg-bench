#!/bin/zsh
# Let an LLM play the game. You supply an OpenAI-compatible endpoint; the
# harness, the game knowledge and the tools are all in this repo.
#
#   export QUNXIA_LLM_BASE_URL=https://api.openai.com/v1
#   export QUNXIA_LLM_API_KEY=sk-...
#   export QUNXIA_LLM_MODEL=gpt-5
#   ./Scripts/play-agent.sh
#
# All arguments are passed to pi, e.g. `./Scripts/play-agent.sh -p "play"`.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

: "${QUNXIA_LLM_BASE_URL:?set QUNXIA_LLM_BASE_URL, e.g. http://localhost:11434/v1}"
: "${QUNXIA_LLM_MODEL:?set QUNXIA_LLM_MODEL, e.g. gpt-5 or qwen3:32b}"
API="${QUNXIA_API:-http://127.0.0.1:8765}"
API="${API%/}"
KEY="${QUNXIA_LLM_API_KEY:-local}"
PI_DIR="${QUNXIA_PI_DIR:-$ROOT/pi-agent}"
AGENT="${QUNXIA_AGENT:-pi}"

command -v curl >/dev/null || { echo "curl not found" >&2; exit 1; }
PI_BIN="$(command -v pi || true)"
[[ -n "$PI_BIN" ]] || { echo "pi not found. Install: npm i -g @earendil-works/pi-coding-agent"; exit 1; }
NODE_BIN="${QUNXIA_NODE:-$(command -v node || true)}"
node_is_compatible() {
  [[ -n "$1" ]] && "$1" -e \
    'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=19)?0:1)' \
    >/dev/null 2>&1
}
if ! node_is_compatible "$NODE_BIN" && node_is_compatible /opt/homebrew/bin/node; then
  NODE_BIN=/opt/homebrew/bin/node
fi
node_is_compatible "$NODE_BIN" || {
  echo "pi requires Node.js >=22.19 (set QUNXIA_NODE to a compatible node binary)" >&2
  exit 1
}
[[ -f "$PI_DIR/SYSTEM.md" && -f "$PI_DIR/extensions/qunxia/index.ts" ]] || {
  echo "Pi game config is incomplete at $PI_DIR" >&2
  exit 1
}

# Generate valid JSON even when model ids or URLs contain punctuation. The file
# contains an environment reference, never the API key itself.
export QUNXIA_LLM_API_KEY="$KEY"
"$NODE_BIN" "$ROOT/Scripts/write-pi-model.mjs" "$PI_DIR/models.json"

# Bring the game up if it is not already answering.
if ! curl -sf -m 2 -H "X-Agent: $AGENT" "$API/help" >/dev/null 2>&1; then
  if [[ "${QUNXIA_AUTO_START:-1}" == "0" ]]; then
    echo "the game is not reachable at $API (automatic start disabled)" >&2
    exit 1
  fi
  echo "starting the game..."
  GAME_LOG="${QUNXIA_GAME_LOG:-${TMPDIR:-/tmp}/qunxia-agent-$$.log}"
  ./Scripts/run.sh >"$GAME_LOG" 2>&1 &
  for i in {1..90}; do
    curl -sf -m 2 -H "X-Agent: $AGENT" "$API/help" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf -m 2 -H "X-Agent: $AGENT" "$API/help" >/dev/null 2>&1 || {
    echo "the game did not come up; see $GAME_LOG"; exit 1; }
  echo "waiting for the title screen..."
  curl -sf -m 60 -X POST "$API/wait?image=0" \
    -H 'content-type: application/json' -H "X-Agent: $AGENT" \
    -d '{"ms":14000}' >/dev/null || true
fi

PI_ARGS=(--provider qunxia --model "$QUNXIA_LLM_MODEL")
# Benchmark-safe default: expose game tools, not shell/file tools that can read
# the repository. Set QUNXIA_ALLOW_CODING_TOOLS=1 for an unrestricted session.
if [[ "${QUNXIA_ALLOW_CODING_TOOLS:-0}" != "1" ]]; then
  PI_ARGS+=(--no-builtin-tools)
fi

exec env PI_CODING_AGENT_DIR="$PI_DIR" QUNXIA_API="$API" QUNXIA_AGENT="$AGENT" \
  QUNXIA_LLM_API_KEY="$KEY" "$NODE_BIN" "$PI_BIN" "${PI_ARGS[@]}" "$@"
