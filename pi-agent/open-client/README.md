# Open-client Pi runs

`benchmark-open-client` allows the model to write files, execute shell commands
and build local CV/OCR programs from its own screenshots. It is a separate,
opt-in protocol, not a change to the `strict` or `benchmark` tool lists.
The game server, scoring and historical paper data are unchanged.

## Build and run

Requires Node >=22.19 and a running local Docker or Podman engine. On macOS,
start Docker Desktop or `podman machine start`. For Podman, set
`QUNXIA_CONTAINER_RUNTIME=podman` on the build, launch and container tests.

```sh
export QUNXIA_CONTAINER_RUNTIME=podman  # omit to use docker
node Scripts/build-open-client.mjs
```

The build copies only the package lock, Pi extension and container adapter
into a temporary context. It never sends the game, repository, credentials,
recordings or other runs to the builder. The image includes pinned Pi 0.84.4,
Node 24.7.0, Python 3, NumPy, Pillow, OpenCV and curl. Debian packages are
resolved when building; keep the same built image for repeated runs.
Extra dependencies must be installed in an audited client image before play,
not downloaded from the web during a run.

Create a new session through the broker as usual, preferably with `publish:
false` while validating a new client protocol. Only a tokenized broker URL is
accepted; a bare native game API is not an isolated scored session.

```sh
# BASE_URL and AGENT come from the same POST /session response.
export QUNXIA_API="${BASE_URL%/}/api"
export QUNXIA_BENCH_AGENT="$AGENT"
export QUNXIA_LLM_BASE_URL=https://your-model-provider.example/v1
export QUNXIA_LLM_MODEL=your-provider/your-model
export QUNXIA_LLM_API_KEY=your-key
export QUNXIA_THINKING=high
export QUNXIA_LLM_REASONING=1
export QUNXIA_LLM_SUPPORTS_REASONING_EFFORT=1
QUNXIA_PI_PROFILE=benchmark-open-client QUNXIA_RUN_ID=cv-01 \
  ./Scripts/play-agent.sh -p "Play until BENCHMARK ENDED."
```

Model definitions and OpenAI Chat, OpenAI Responses and Gemini adapters work
as in the ordinary launcher. The container is non-interactive: `-p`,
`--mode text|json` and prompt text are accepted, not arbitrary Pi options or
host file attachments. Host `npm ci` is not needed for this profile: Pi runs
from the image. `QUNXIA_CLIENT_IMAGE` selects an already-built trusted image;
it is checked locally before launch and is never pulled during play.
Unknown or unavailable runtimes/images fail closed.

`QUNXIA_RUNS_DIR` changes the host artifact root (default `.runs/pi`). A run
must be new unless `QUNXIA_RESUME=1`; resuming requires the same session, model,
tools, image name and isolation configuration. Do not replace the image behind
that name while a run is resumable. Simultaneous resumes are refused.
Do not start a different profile with an existing run ID. A hard-killed host
launcher can leave `.open-client-active`; confirm its container is gone before
removing that marker and resuming. Never reuse a run directory for a new session.

## Enforcement

- Each run gets a distinct container, a private PID/IPC/network namespace and
  only two mounts: its own `client/` directory read/write, and sanitized
  launch configuration read-only. No host home, shared `/tmp`, repository,
  game/ROM, server, saves, other runs, or container socket is mounted.
- The root filesystem is read-only, the user is non-root, all capabilities
  are dropped, no-new-privileges is enabled, and resource limits are 2 CPUs,
  2 GiB RAM, 128 processes and a 256 MiB `/tmp`. `HOME`, temporary, config,
  cache, sessions and workspace paths belong to this run alone.
- `--network=none` leaves only the container's loopback interface. The local
  HTTP adapter sends requests over stdio to the host. Its messages are
  untrusted: host policy constructs the destination and credentials itself.
  Shell programs can use the same adapter but cannot bypass host validation.
- Game traffic is pinned to the supplied session URL. Only `GET /api/screen`,
  `GET /api/help`, `GET /api/keys` and `POST /api/key` are forwarded. Queries
  are allowlisted; scale stays at 1 and `spectate=1` is rejected. Client
  identity/operator headers are discarded. Other sessions, spectator sockets,
  status, recordings, catalogues, history, reset and snapshots are unreachable.
- Model traffic only reaches the selected model's inference endpoint. Hosted
  search/tools, remote media URLs, provider file inputs, stored conversation
  references and redirects are rejected. The provider key is added on the
  host; the container only holds a dummy credential.
- The session clock is read before container startup from
  `X-Bench-Remaining`. Boot, local code and CV all consume that budget. At
  expiry, or when the launcher is interrupted, its container and descendant
  processes are removed. Local work cannot pause or reset the game clock.

`game_look` saves each observed PNG under `/client/workspace/frames` as well as
returning it to the model. Built-in `read` can view it and local Python can
compare frames. The independent `Scripts/play.py` helper now defaults to a
private temporary directory, not shared `/tmp/qunxia.png`;
this naming fix alone is not a security boundary for host-native clients.

## Evidence and limits

Host-only `run.json` records the profile, declared tools, model and brief;
`isolation.json` records the client image name, runtime version, mounts and
limits. `nodeVersion` in `run.json` is the host preparation runtime; the
client Node version belongs to the selected image.
`network.jsonl` records allowed and denied requests, status, bytes and elapsed
time without model credentials or request bodies. `launch.json` identifies
the container and launcher for recovery after a host crash; `exit.json`
records the observed container exit and timeout. These records are outside the client
mount. `client/` contains the model's own sessions, code and screenshots.

Client files, including Pi session logs, are model-writable and untrusted.
The host does not read/execute them on resume or publish their token/cost
claims via `/usage`. Trusted provider-side billing aggregation is not part of
this change. Do not follow client-created symlinks or execute its scripts on
the host when inspecting artifacts.

Report and group open-client runs by their profile and image, separately from
game-tool-only runs. The existing public board is not an attestation service
and is not made into a separate ranking by this change; use unpublished
sessions for protocol validation. The launcher does not secure arbitrary
third-party clients that connect to the public broker outside this boundary.

The operator, container engine and selected runtime image are trusted. A
malicious operator can still preload answers or choose a different image.
Containers do not defend against kernel/runtime vulnerabilities. For hostile
multi-tenant clients, use a dedicated VM/host and host-level artifact disk
quotas; CPU/memory/PID limits do not bound the persistent artifact directory.
Use a local engine: bind mounts are paths on the engine's host, not a remote
Docker context or arbitrary SSH server.

## Tests

```sh
npm run test:pi-runner
npm run test:open-client             # policy tests; container cases skip by default
QUNXIA_TEST_CONTAINER=1 npm run test:open-client
python3 -m unittest Scripts.test_agent_launchers
```

Two small policy checks cover the game and inference boundaries. The container
smoke tests run two real Pi clients concurrently, execute all six tools and
local CV, check host/network isolation, and stop shell work at the deadline.
They use scripted endpoints, not paid providers. Enable them explicitly with
a local container engine; skipped cases do not verify isolation.
