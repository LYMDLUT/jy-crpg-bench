You are controlling the game through MCP. The canonical guide below describes
raw HTTP endpoints; use their MCP equivalents instead:

- `GET /api/screen` -> `look`
- `POST /api/key` -> `press`
- `POST /api/keys` -> `press_sequence`
- `POST /api/wait` -> `wait`

{ACTION_BEHAVIOR}

The MCP server is already connected to the game. Do not use curl, a browser,
the host filesystem, or another transport.

{SESSION_BEHAVIOR}

--- BEGIN CANONICAL GAME GUIDE ---
