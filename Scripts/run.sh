#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."

# The game data lives in the repo as one compressed archive; unpack on first run.
if [[ ! -f game/PLAY.BAT && -f assets/game-data.tar.gz ]]; then
  echo "unpacking game data..."
  mkdir -p game
  tar xzf assets/game-data.tar.gz
fi

swift build -c release
exec ./.build/release/QunXia "$@"
