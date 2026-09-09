# Persistent interactive sessions

This gateway preserves `user.json` identities and `/u/<id>/` addresses across
restarts. Workers start on demand and use independent `game/` and `saves/`
directories. It requires the server's opt-in persistent checkpoint support;
it refuses a worker that cannot report a ready checkpoint lifecycle.

Run with the same Python environment as the headless server:

```sh
python server/multiuser.py serve \
  --users-dir /srv/qunxia/users \
  --core /srv/qunxia/cores/dosbox_pure_libretro.so \
  --game-dir /srv/qunxia/game-template \
  --host 127.0.0.1 --port 8084
```

`--game-dir` is needed only to create new users and must contain `PLAY.BAT`.
Existing user directories keep their metadata, game, `saves/live.state`,
manual slots and `saves/recording.jsonl`. The existing RecordingStore opens
that JSONL directly; no log conversion or startup replay indexing occurs.
`QUNXIA_USERS_DIR`, `QUNXIA_CORE`, `QUNXIA_GAME_DIR`,
`QUNXIA_MULTIUSER_HOST` and `PORT` provide the corresponding defaults.
`QUNXIA_MAX_USERS=0` leaves user count uncapped. This is a local/shared gateway,
not an account authentication system; the lobby lists the available sessions.

Workers always bind to loopback and use the opt-in checkpoint path. The normal
checkpoint interval and warmup settings apply. Benchmark mode, calibration and
the menu-save macro are disabled for these persistent interactive workers.
Each worker's watchdog state is kept under its own `saves/.health/` directory,
with diagnostics under `saves/.health/incidents/`; gateway-level
`QUNXIA_HEALTH_DIR` and `QUNXIA_DIAGNOSTIC_DIR` values cannot make workers
share these files.
The gateway waits for `checkpoint.state=ready`; a failed resume is reported
instead of accepting input into a fresh game. Asset, help, WebSocket and
recording requests resolve relative to the session URL. For a reverse proxy,
`QUNXIA_PUBLIC_BASE` can supply the public origin used in copied API help.

A directory lease prevents two gateways using the same root; an inherited
per-user lease prevents duplicate workers. A parent pipe makes an orphaned
worker exit cleanly. Shutdown waits up to 15 seconds for each owned worker's
checkpoint before terminating a stuck worker. Unknown live legacy PIDs are
refused, never killed based solely on a stale marker.

The existing browser replay and MediaRecorder export remain available. This
gateway does not add the separate legacy cached/cancellable export service or
its job endpoints. A local migration that depends on those endpoints needs an
explicit compatibility adapter before replacing its old entry point.
