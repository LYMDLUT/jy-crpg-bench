"""Persistent, process-isolated interactive sessions under /u/<id>/.

The users directory is explicit. Each existing user.json, game and saves tree
keeps its identity across gateway restarts. No benchmark session is resumed.
"""
import argparse
import asyncio
from dataclasses import dataclass
import fcntl
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

HERE = Path(__file__).resolve().parent
USER_ID = re.compile(r"[A-Za-z0-9_-]{20,64}")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailer", "trailers", "transfer-encoding", "upgrade", "content-length"}


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class UserStore:
    def __init__(self, root, game=None, max_users=0):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.game = Path(game).resolve() if game else None
        self.max_users = max(0, max_users)

    def paths(self, identity):
        if not USER_ID.fullmatch(identity):
            raise ValueError("invalid user id")
        base = self.root / identity
        for path in (base, base / "game", base / "saves"):
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError("session paths must stay inside the users directory")
        return base, base / "game", base / "saves"

    def get(self, identity):
        try:
            path = self.paths(identity)[0] / "user.json"
            if path.is_symlink() or path.stat().st_size > 65536:
                return None
            user = json.loads(path.read_text())
            if (user.get("id") == identity and isinstance(user.get("name"), str)
                    and isinstance(user.get("created_at"), (float, int))):
                return user
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def all(self):
        users = [self.get(path.name) for path in self.root.iterdir()
                 if USER_ID.fullmatch(path.name)]
        return sorted((u for u in users if u), key=lambda u: u["created_at"])

    def create(self, name):
        name = " ".join(str(name).split())
        if not 1 <= len(name) <= 40:
            raise ValueError("name must contain 1-40 characters")
        if self.max_users and len(self.all()) >= self.max_users:
            raise ValueError("user limit reached")
        if not self.game or not (self.game / "PLAY.BAT").is_file():
            raise ValueError("configure a game template directory containing PLAY.BAT")
        identity = secrets.token_urlsafe(18)
        base, game, saves = self.paths(identity)
        base.mkdir(mode=0o700)
        try:
            shutil.copytree(self.game, game)
            saves.mkdir()
            user = {"id": identity, "name": name, "created_at": time.time(), "default": False}
            atomic_json(base / "user.json", user)
            return user
        except BaseException:
            shutil.rmtree(base)
            raise


@dataclass
class Backend:
    process: subprocess.Popen
    port: int
    log: object
    parent_pipe: int
    marker: Path


class BackendManager:
    def __init__(self, store, core, *, python=sys.executable, server=HERE / "server.py",
                 startup_timeout=90, shutdown_timeout=15, environment=None):
        self.store, self.core = store, str(core)
        self.python, self.server = python, Path(server)
        self.startup_timeout, self.shutdown_timeout = startup_timeout, shutdown_timeout
        self.environment = environment or {}
        self.backends, self.locks = {}, {}
        self.client = None
        self.lease = None
        self.closing = False

    async def start(self):
        self.lease = os.open(self.store.root / ".gateway.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lease)
            self.lease = None
            raise RuntimeError("another gateway owns this users directory")
        self.client = ClientSession(timeout=ClientTimeout(total=120), auto_decompress=False)

    async def stop(self, backend):
        if backend.process.poll() is None:
            backend.process.terminate()
            try:
                await asyncio.to_thread(backend.process.wait, timeout=self.shutdown_timeout)
            except subprocess.TimeoutExpired:
                backend.process.kill()
                await asyncio.to_thread(backend.process.wait)
        if backend.parent_pipe is not None:
            os.close(backend.parent_pipe)
            backend.parent_pipe = None
        backend.log.close()
        backend.marker.unlink(missing_ok=True)

    async def ensure(self, user):
        identity = user["id"]
        async with self.locks.setdefault(identity, asyncio.Lock()):
            if self.closing:
                raise RuntimeError("gateway is shutting down")
            old = self.backends.get(identity)
            if old and old.process.poll() is None:
                return old
            if old:
                await self.stop(old)
                self.backends.pop(identity, None)
            base, game, saves = self.store.paths(identity)
            marker = base / "backend.json"
            lease = os.open(base / ".backend.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # A legacy marker is not proof that we own its PID. Refuse a
                # live unknown owner instead of signalling an unrelated process.
                if marker.exists():
                    try:
                        pid = int(json.loads(marker.read_text())["pid"])
                    except (OSError, ValueError, KeyError, TypeError):
                        pid = 0
                    if pid > 0:
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            pass
                        else:
                            raise RuntimeError("a previous backend may still own this session")
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                read_fd, write_fd = os.pipe()
                log = (base / "server.log").open("ab", buffering=0)
                environment = dict(os.environ, **self.environment)
                for name in ("QUNXIA_RESET_TOKEN", "QUNXIA_PARENT_PID", "QUNXIA_RUNTIME_DIR",
                             "QUNXIA_SESSION_DIR", "QUNXIA_BENCH_SID"):
                    environment.pop(name, None)
                environment.update(PORT=str(port), QUNXIA_HOST="127.0.0.1",
                    QUNXIA_CORE=self.core, QUNXIA_GAME=str(game / "PLAY.BAT"),
                    QUNXIA_SAVES=str(saves), QUNXIA_STATE_DIR=str(saves / "states"),
                    QUNXIA_START_STATE=str(saves / "start.state"),
                    QUNXIA_RESUME_STATE=str(saves / "live.state"),
                    QUNXIA_RECORDING_DIR=str(saves), QUNXIA_RECORDING_FILE=str(saves / "recording.jsonl"),
                    QUNXIA_BENCH="0", QUNXIA_CALIBRATE="0", QUNXIA_SNAPSHOT_EVERY="0",
                    QUNXIA_PARENT_FD=str(read_fd))
                try:
                    process = subprocess.Popen([self.python, "-u", str(HERE / "session_worker.py"),
                                                str(self.server)], cwd=self.server.parent,
                        env=environment, stdout=log, stderr=log, pass_fds=(read_fd, lease),
                        start_new_session=True)
                except BaseException:
                    os.close(write_fd)
                    log.close()
                    raise
                finally:
                    os.close(read_fd)
                backend = Backend(process, port, log, write_fd, marker)
                self.backends[identity] = backend
            finally:
                # The inherited descriptor keeps the per-user lease until
                # the worker exits, even if the gateway is killed.
                os.close(lease)
            try:
                atomic_json(marker, {"pid": process.pid, "port": port, "started_at": time.time()})
                deadline = asyncio.get_running_loop().time() + self.startup_timeout
                while process.poll() is None and asyncio.get_running_loop().time() < deadline:
                    try:
                        async with self.client.get(f"http://127.0.0.1:{port}/status", timeout=1) as response:
                            status = await response.json()
                        checkpoint = status.get("checkpoint", {})
                        if checkpoint.get("state") == "failed":
                            raise RuntimeError("session restore failed: " + str(checkpoint.get("error")))
                        if response.status == 200 and status.get("healthy"):
                            if not checkpoint.get("enabled"):
                                raise RuntimeError("the worker needs persistent checkpoint support")
                            if checkpoint.get("state") == "ready":
                                return backend
                    except (OSError, asyncio.TimeoutError):
                        pass
                    await asyncio.sleep(.1)
                raise RuntimeError("backend did not become ready; inspect its server.log")
            except BaseException:
                await asyncio.shield(self.stop(backend))
                self.backends.pop(identity, None)
                raise

    async def close(self):
        self.closing = True
        await asyncio.gather(*(self.stop(b) for b in self.backends.values()))
        self.backends.clear()
        if self.client:
            await self.client.close()
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None


def forwarded_headers(request, identity, public_origin=None):
    excluded = HOP | {s.strip().lower() for s in request.headers.get("Connection", "").split(",")}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded
               and k.lower() != "host" and not k.lower().startswith(("x-forwarded-", "sec-websocket-"))}
    origin = urlsplit(public_origin) if public_origin else None
    headers.update({"Host": request.host,
                    "X-Forwarded-Host": origin.netloc if origin else request.host,
                    "X-Forwarded-Proto": origin.scheme if origin else request.scheme,
                    "X-Forwarded-Prefix": f"/u/{identity}"})
    return headers


async def relay(source, destination):
    async for message in source:
        if message.type == WSMsgType.TEXT:
            await destination.send_str(message.data)
        elif message.type == WSMsgType.BINARY:
            await destination.send_bytes(message.data)
        else:
            break


def build_app(store, manager, public_origin=None):
    app = web.Application(client_max_size=4 << 20)
    create_lock = asyncio.Lock()
    connections = set()

    async def lobby(_request):
        rows = "".join(f'<li><a href="/u/{u["id"]}/">{html.escape(u["name"])}</a></li>' for u in store.all())
        return web.Response(content_type="text/html", text='''<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Persistent sessions</title>
<style>body{max-width:38rem;margin:3rem auto;padding:1rem;font:18px system-ui;line-height:1.6}
input,button{font:inherit;padding:.4rem}li{margin:.5rem 0}</style><h1>Persistent sessions</h1>
<p>Each player has a separate game, saves and recording. Opening a session can take a moment.</p>
<ul>''' + rows + '''</ul><form><input name="name" maxlength="40" required placeholder="Player name">
<button>Create session</button></form><p id="message"></p><script>
document.querySelector('form').onsubmit=async e=>{e.preventDefault();
const r=await fetch('api/users',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({name:new FormData(e.target).get('name')})});const d=await r.json();
if(r.ok)location.href=d.url;else document.querySelector('#message').textContent=d.error;};</script>''')

    async def users(_request):
        entries = store.all()
        return web.json_response({"users": len(entries), "max_users": store.max_users or None,
                                  "items": entries, "active": len(manager.backends)})

    async def create(request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            async with create_lock:
                user = await asyncio.to_thread(store.create, body.get("name", ""))
            return web.json_response({"ok": True, "id": user["id"], "url": f'/u/{user["id"]}/'}, status=201)
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def proxy(request):
        identity = request.match_info["identity"]
        user = store.get(identity)
        if not user:
            raise web.HTTPNotFound()
        if "tail" not in request.match_info:
            raise web.HTTPFound(f"/u/{identity}/")
        try:
            backend = await manager.ensure(user)
        except (OSError, RuntimeError) as exc:
            return web.json_response({"error": str(exc)}, status=503)
        target = f'http://127.0.0.1:{backend.port}/{request.match_info["tail"]}'
        if request.query_string:
            target += "?" + request.rel_url.raw_query_string
        headers = forwarded_headers(request, identity, public_origin)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            upstream = await manager.client.ws_connect(target, headers=headers, max_msg_size=4 << 20,
                                                        compress=0)
            downstream = web.WebSocketResponse(max_msg_size=4096, compress=False)
            pair = (downstream, upstream, request.transport)
            connections.add(pair)
            tasks = []
            try:
                if manager.closing:
                    raise web.HTTPServiceUnavailable()
                await downstream.prepare(request)
                tasks = [asyncio.create_task(relay(a, b)) for a, b in
                         ((downstream, upstream), (upstream, downstream))]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                connections.discard(pair)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await upstream.close()
                await downstream.close()
            return downstream
        async with manager.client.request(request.method, target, headers=headers,
                data=request.content.iter_chunked(64 << 10), allow_redirects=False) as upstream:
            headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP}
            if headers.get("Location", "").startswith("/"):
                headers["Location"] = f"/u/{identity}" + headers["Location"]
            downstream = web.StreamResponse(status=upstream.status, headers=headers)
            if upstream.content_length is not None:
                downstream.content_length = upstream.content_length
            await downstream.prepare(request)
            try:
                async for chunk in upstream.content.iter_chunked(64 << 10):
                    await downstream.write(chunk)
                await downstream.write_eof()
            except ConnectionError:
                pass
            return downstream

    async def start(_app):
        await manager.start()

    async def close(_app):
        await manager.close()

    async def shutdown(_app):
        # on_cleanup is too late: aiohttp first waits for open request handlers,
        # including these long-lived WebSockets. End both halves before drain.
        manager.closing = True
        active = list(connections)
        try:
            await asyncio.wait_for(asyncio.gather(
                *(socket.close() for pair in active for socket in pair[:2]),
                return_exceptions=True), timeout=2)
        except asyncio.TimeoutError:
            pass
        finally:
            for _downstream, _upstream, transport in active:
                if transport:
                    transport.close()

    app.router.add_get("/", lobby)
    app.router.add_get("/health", users)
    app.router.add_get("/api/users", users)
    app.router.add_post("/api/users", create)
    app.router.add_get("/u/{identity}", proxy)
    app.router.add_route("*", "/u/{identity}/{tail:.*}", proxy)
    app.on_startup.append(start)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(close)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "list", "create"))
    parser.add_argument("--users-dir", default=os.environ.get("QUNXIA_USERS_DIR"))
    parser.add_argument("--game-dir", default=os.environ.get("QUNXIA_GAME_DIR"))
    parser.add_argument("--core", default=os.environ.get("QUNXIA_CORE"))
    parser.add_argument("--name")
    parser.add_argument("--host", default=os.environ.get("QUNXIA_MULTIUSER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8084")))
    args = parser.parse_args()
    if not args.users_dir:
        parser.error("set --users-dir or QUNXIA_USERS_DIR")
    store = UserStore(args.users_dir, args.game_dir, int(os.environ.get("QUNXIA_MAX_USERS", "0")))
    if args.command == "list":
        print(json.dumps(store.all(), ensure_ascii=False, indent=2))
    elif args.command == "create":
        print(json.dumps(store.create(args.name or ""), ensure_ascii=False))
    else:
        if not args.core:
            parser.error("set --core or QUNXIA_CORE")
        manager = BackendManager(store, args.core)
        web.run_app(build_app(store, manager, os.environ.get("QUNXIA_PUBLIC_BASE")),
                    host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
