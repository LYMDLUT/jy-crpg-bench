#!/bin/zsh
# Regenerate assets/game-data.tar.gz from the working game/ directory.
set -euo pipefail
cd "$(dirname "$0")/.."
COPYFILE_DISABLE=1 tar --exclude='.DS_Store' --exclude='._*' \
  -czf assets/game-data.tar.gz game
ls -lh assets/game-data.tar.gz
