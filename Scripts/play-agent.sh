#!/bin/zsh
# Let an LLM play the game. You supply an OpenAI-compatible endpoint; the
# harness, the game knowledge and the tools are all in this repo.
#
#   export QUNXIA_LLM_BASE_URL=https://api.openai.com/v1
#   export QUNXIA_LLM_API_KEY=sk-...
#   export QUNXIA_LLM_MODEL=gpt-5
#   ./Scripts/play-agent.sh
#
# Anything after -- is passed to pi, e.g. `./Scripts/play-agent.sh -p "play"`.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

: "${QUNXIA_LLM_BASE_URL:?set QUNXIA_LLM_BASE_URL, e.g. http://localhost:11434/v1}"
: "${QUNXIA_LLM_MODEL:?set QUNXIA_LLM_MODEL, e.g. gpt-5 or qwen3:32b}"
API="${QUNXIA_API:-http://127.0.0.1:8765}"
KEY="${QUNXIA_LLM_API_KEY:-local}"
# Vision is how the agent sees the game. Set to text if your model has none.
INPUT="${QUNXIA_LLM_INPUT:-\"text\", \"image\"}"
CTX="${QUNXIA_LLM_CONTEXT:-128000}"

command -v pi >/dev/null || { echo "pi not found. Install: npm i -g @earendil-works/pi-coding-agent"; exit 1; }

cat > pi-agent/models.json <<JSON
{
  "providers": {
    "qunxia": {
      "baseUrl": "${QUNXIA_LLM_BASE_URL}",
      "api": "openai-completions",
      "apiKey": "${KEY}",
      "compat": { "supportsDeveloperRole": false, "supportsReasoningEffort": false },
      "models": [
        {
          "id": "${QUNXIA_LLM_MODEL}",
          "name": "${QUNXIA_LLM_MODEL}",
          "input": [${INPUT}],
          "contextWindow": ${CTX},
          "maxTokens": 8192,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
  }
}
JSON

# Bring the game up if it is not already answering.
if ! curl -sf -m 2 "$API/state?image=0" >/dev/null 2>&1; then
  echo "starting the game..."
  ./Scripts/run.sh >/tmp/qunxia-agent.log 2>&1 &
  for i in {1..90}; do
    curl -sf -m 2 "$API/state?image=0" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf -m 2 "$API/state?image=0" >/dev/null 2>&1 || {
    echo "the game did not come up; see /tmp/qunxia-agent.log"; exit 1; }
  echo "waiting for the title screen..."
  curl -sf -m 60 -X POST "$API/wait?image=0" -d '{"ms":14000}' >/dev/null || true
fi

exec env PI_CODING_AGENT_DIR="$ROOT/pi-agent" QUNXIA_API="$API" \
  pi --provider qunxia --model "$QUNXIA_LLM_MODEL" "$@"
