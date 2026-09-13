#!/usr/bin/env python3
"""Play a scored session by hand, through the same control API a model uses.

  ./Scripts/human_play.py --agent human-1 --minutes 60
  ./Scripts/human_play.py --base-url https://.../s/<id>/t/<token>   # attach to a session

The script asks the benchmark for a session (or attaches to one), then serves a
page on this machine that shows the frame the API returns and sends every key
you press as one POST /api/key, the single-key action a model may also send.
After each action it fetches the screen once, which is the look a model makes
when it wants to see the result. The brief the models read is one click away
and is fetched through the same API, so the clock is running while you read
it, as it runs for a model.

The page talks only to this script; the script talks to the session, so the
token never leaves this machine and the browser needs no cross-origin access.
The session is recorded, scored and published like any other unless
--no-publish is given, which is meant for trying the client out.

Keys: arrows and the numpad move (the game aliases the arrows onto the four
diagonals); the main-row digits 1 3 7 9 stand in for the numpad on a laptop;
Enter confirms, Escape opens the menu, y and n answer a prompt, letters pass
through. Held keys do not repeat: one press is one step.
"""
import argparse
import http.server
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

DEFAULT_BACKEND = "https://jy-crpg-bench-366646433082.us-central1.run.app"

PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>jy-crpg-bench: human session</title>
<style>
  body { margin: 0; background: #111; color: #ddd; font: 14px/1.4 -apple-system, Helvetica, Arial, sans-serif; }
  header { display: flex; gap: 18px; align-items: baseline; padding: 10px 16px; background: #1a1a20; }
  header b { color: #fff; }
  #remaining { font-variant-numeric: tabular-nums; }
  main { display: flex; flex-direction: column; align-items: center; padding: 14px; gap: 10px; }
  #frame { width: 960px; height: 600px; image-rendering: pixelated; background: #000; border: 1px solid #333; }
  #log { width: 960px; color: #9a9aa2; font-family: ui-monospace, Menlo, monospace; font-size: 12px; white-space: pre-wrap; min-height: 3em; }
  a { color: #8ab4f8; }
  .ended { color: #f28b82; }
</style>
<header>
  <b>jy-crpg-bench</b>
  <span>session <code id="sid"></code></span>
  <span>remaining <span id="remaining">--:--</span></span>
  <span>actions <span id="count">0</span></span>
  <a href="/brief" target="_blank">the brief (agents.md)</a>
  <span id="state"></span>
</header>
<main>
  <img id="frame" alt="the game frame">
  <div id="log">click the frame, then press keys; the page sends one API action per key press and looks once after it</div>
</main>
<script>
const MAP = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
             Enter: "enter", Escape: "escape", " ": "space", Backspace: "backspace", Tab: "tab"};
const DIGITS = {"1": "kp1", "2": "kp2", "3": "kp3", "4": "kp4", "6": "kp6", "7": "kp7", "8": "kp8", "9": "kp9"};
let count = 0, remaining = null, ended = false, busy = false, queue = [];
const $ = id => document.getElementById(id);
$("sid").textContent = SESSION_ID;
function keyName(e) {
  if (e.code && e.code.startsWith("Numpad") && e.code.length === 7) return "kp" + e.code[6];
  if (MAP[e.key]) return MAP[e.key];
  if (DIGITS[e.key]) return DIGITS[e.key];
  if (e.key.length === 1 && /[a-z]/i.test(e.key)) return e.key.toLowerCase();
  return null;
}
function tick() {
  if (remaining === null) return;
  remaining = Math.max(0, remaining - 1);
  const m = Math.floor(remaining / 60), s = remaining % 60;
  $("remaining").textContent = m + ":" + String(s).padStart(2, "0");
}
setInterval(tick, 1000);
async function look() {
  const r = await fetch("/screen?t=" + Date.now(), {cache: "no-store"});
  if (r.status === 410) { finish(await r.text()); return; }
  const rem = r.headers.get("X-Remaining");
  if (rem !== null) remaining = parseInt(rem, 10);
  const blob = await r.blob();
  $("frame").src = URL.createObjectURL(blob);
}
function finish(text) {
  ended = true;
  $("state").textContent = "session ended";
  $("state").className = "ended";
  $("log").textContent = text;
}
async function pump() {
  if (busy || ended || !queue.length) return;
  busy = true;
  const key = queue.shift();
  try {
    const r = await fetch("/key", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key})});
    const text = await r.text();
    if (r.status === 410) { finish(text); return; }
    const rem = r.headers.get("X-Remaining");
    if (rem !== null) remaining = parseInt(rem, 10);
    count += 1;
    $("count").textContent = count;
    $("log").textContent = "#" + count + " " + key + " -> " + text.slice(0, 200);
    await look();
  } catch (err) {
    $("log").textContent = "error: " + err;
  } finally {
    busy = false;
    pump();
  }
}
addEventListener("keydown", e => {
  if (e.repeat || e.metaKey || e.ctrlKey || e.altKey || ended) return;
  const key = keyName(e);
  if (!key) return;
  e.preventDefault();
  if (queue.length < 4) queue.push(key);
  pump();
});
look();
</script>
"""


class Relay(http.server.BaseHTTPRequestHandler):
    base = ""
    session = ""
    lang = "en"

    def log_message(self, fmt, *args):      # one line per relayed call, no token
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def upstream(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def reply(self, status, body, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        remaining = (headers or {}).get("X-Bench-Remaining")
        if remaining is not None:
            self.send_header("X-Remaining", remaining)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            page = PAGE.replace("SESSION_ID", json.dumps(self.session), 1).encode()
            return self.reply(200, page, "text/html; charset=utf-8")
        if path == "/screen":
            status, headers, body = self.upstream("GET", "/api/screen?format=png")
            if status == 200:
                return self.reply(200, body, "image/png", headers)
            return self.reply(status, body, headers.get("Content-Type", "application/json"), headers)
        if path == "/favicon.ico":
            return self.reply(204, b"", "image/x-icon")
        if path == "/brief":
            status, headers, body = self.upstream("GET", "/api/help?lang=" + self.lang)
            return self.reply(status, body, "text/plain; charset=utf-8", headers)
        return self.reply(404, b"not found", "text/plain")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/key":
            return self.reply(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length", "0"))
        try:
            key = json.loads(self.rfile.read(length) or b"{}").get("key")
        except ValueError:
            key = None
        if not key:
            return self.reply(400, b'{"ok": false, "error": "key required"}', "application/json")
        status, headers, body = self.upstream("POST", "/api/key", {"key": key})
        return self.reply(status, body, headers.get("Content-Type", "application/json"), headers)


def create_session(backend, agent, minutes, publish):
    req = urllib.request.Request(backend + "/session", method="POST",
                                 data=json.dumps({"agent": agent, "minutes": minutes,
                                                  "publish": publish}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=DEFAULT_BACKEND, help="the benchmark service")
    ap.add_argument("--agent", default="human-1", help="the name the session is listed under")
    ap.add_argument("--minutes", type=int, default=60, help="the budget")
    ap.add_argument("--lang", default="en", choices=("en", "zh"), help="language of the brief")
    ap.add_argument("--base-url", help="attach to an existing session instead of creating one")
    ap.add_argument("--no-publish", action="store_true", help="a trial run that stays out of the catalogue")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if args.base_url:
        base = args.base_url.rstrip("/")
        session = base.split("/s/")[1].split("/")[0] if "/s/" in base else "?"
    else:
        info = create_session(args.backend.rstrip("/"), args.agent, args.minutes, not args.no_publish)
        base, session = info["base_url"].rstrip("/"), info["session"]
        print("session %s for %s, %s minutes%s" % (session, info["agent"], info["minutes"],
                                                     "" if not args.no_publish else " (not published)"))
        print("spectators: %s/s/%s" % (args.backend.rstrip("/"), session))
    print("play at http://127.0.0.1:%d/  (the session token stays in this process)" % args.port)
    Relay.base, Relay.session, Relay.lang = base, session, args.lang
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Relay)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, ["http://127.0.0.1:%d/" % args.port]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
