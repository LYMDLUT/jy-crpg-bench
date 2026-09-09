"""Gateway transport/ownership fixture; no native core or game required."""
import os
from pathlib import Path

from aiohttp import web

app = web.Application()


async def status(request):
    return web.json_response({"healthy": True,
        "checkpoint": {"enabled": True, "state": os.environ.get("PROBE_PHASE", "ready")},
        "pid": os.getpid(), "saves": os.environ["QUNXIA_SAVES"],
        "recording": os.environ["QUNXIA_RECORDING_FILE"],
        "health": os.environ["QUNXIA_HEALTH_DIR"],
        "diagnostic": os.environ["QUNXIA_DIAGNOSTIC_DIR"],
        "listen_host": os.environ["QUNXIA_HOST"],
        "prefix": request.headers.get("X-Forwarded-Prefix"),
        "bench": os.environ["QUNXIA_BENCH"]})


async def text(request):
    return web.Response(text=request.path)


async def websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for message in ws:
        if message.data == "close":
            await ws.close()
            break
        await ws.send_str(message.data)
    return ws


async def recording(_request):
    return web.Response(body=b"old recording bytes\n", headers={"Content-Type": "application/x-ndjson"})


async def close(_app):
    folder = Path(os.environ["QUNXIA_SAVES"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clean-exit").write_text("closed")


app.add_routes([web.get("/status", status), web.get("/", text),
                web.get("/recording.js", text), web.get("/api/help", text),
                web.get("/api/recording", recording), web.get("/ws", websocket)])
app.on_cleanup.append(close)
web.run_app(app, host=os.environ["QUNXIA_HOST"], port=int(os.environ["PORT"]), access_log=None)
