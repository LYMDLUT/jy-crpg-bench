#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."

# Unpack the game archive on first run, if one has been supplied.
if [[ ! -f game/PLAY.BAT ]]; then
  if [[ -f assets/game-data.tar.gz ]]; then
    echo "unpacking game data..."
    mkdir -p game
    tar xzf assets/game-data.tar.gz
  else
    echo "No game data found. This repository does not ship the game." >&2
    echo "Put the original files in ./game (PLAY.BAT, Z.COM, DOS4GW.EXE and" >&2
    echo "the data files), or build assets/game-data.tar.gz from a copy you" >&2
    echo "own with ./Scripts/pack-game.sh." >&2
    exit 1
  fi
fi

swift build -c release
exec ./.build/release/QunXia "$@"
