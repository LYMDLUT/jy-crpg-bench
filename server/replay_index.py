"""Disposable sparse seek metadata for an existing pinned JSONL snapshot."""
import base64
from contextlib import closing
import hashlib
import json
import math
import os
import sqlite3
import struct
import threading
import zlib

INDEX_LOCK = threading.Lock()


def whole_frame(event):
    data = event.get("d")
    if not isinstance(data, str):
        return False
    try:
        # Reject ordinary deltas from their header; only complete-frame
        # candidates need a full bounded decode. Old k markers are not trusted.
        raw = base64.b64decode(data[:4096], validate=True)
        header = zlib.decompressobj().decompress(raw, 13)
        if len(header) != 13:
            return False
        _flag, w, h, tw, th, cols, rows, count = struct.unpack("<BHHBBHHH", header)
        if not (0 < w <= 2048 and 0 < h <= 2048 and tw > 0 and th > 0
                and cols == (w + tw - 1) // tw and rows == (h + th - 1) // th
                and count == cols * rows):
            return False
        expected = 13 + count * (2 + tw * th * 3)
        if expected > 16 << 20:
            return False
        inflater = zlib.decompressobj()
        payload = inflater.decompress(base64.b64decode(data, validate=True), expected + 1)
        if len(payload) != expected or not inflater.eof:
            return False
        indices = struct.unpack_from(f"<{count}H", payload, 13)
        return len(set(indices)) == count and all(index < count for index in indices)
    except (ValueError, zlib.error, struct.error):
        return False


class SeekIndex:
    def __init__(self, source):
        from recording import Snapshot
        stat = os.fstat(source.fd)
        directory = source.path.parent / ".replay-index"
        directory.mkdir(exist_ok=True)
        self.path = directory / f"{stat.st_dev}-{stat.st_ino}.sqlite3"
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.scanned = source.begin
        self.total = source.end
        self.source = Snapshot(source.path, os.dup(source.fd), source.end, source.duration)
        try:
            self.thread = threading.Thread(target=self.build, daemon=True)
            self.thread.start()
        except BaseException:
            self.source.close()
            raise

    def build(self):
        db = None
        acquired = False
        try:
            while not self.cancelled.is_set():
                if INDEX_LOCK.acquire(timeout=.1):
                    acquired = True
                    break
            if not acquired:
                return
            db = sqlite3.connect(self.path)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA cache_size=-2048")
            db.execute("PRAGMA temp_store=FILE")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS frames (off INTEGER PRIMARY KEY, t REAL, held TEXT);
                CREATE INDEX IF NOT EXISTS frame_time ON frames(t,off);
                CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY, value TEXT);
            """)
            row = db.execute("SELECT value FROM metadata WHERE id=1").fetchone()
            progress = json.loads(row[0]) if row else {}
            signature = hashlib.sha256(json.dumps(self.source.header, sort_keys=True).encode()).hexdigest()
            if (progress.get("header") != signature
                    or progress.get("end", 0) > os.fstat(self.source.fd).st_size):
                db.execute("DELETE FROM frames")
                progress = {}
            start = progress.get("end", self.source.begin)
            self.scanned = min(start, self.total)
            last = progress.get("last", 0.0)
            held = progress.get("held", {})
            if start < self.total:
                for offset, line in self.source.lines(start):
                    if self.cancelled.is_set():
                        return
                    event = json.loads(line)
                    when = float(event["t"])
                    if not math.isfinite(when) or when < 0:
                        raise ValueError("invalid recording timestamp")
                    last = max(last, when)
                    if whole_frame(event):
                        db.execute("INSERT OR REPLACE INTO frames VALUES (?,?,?)",
                                   (offset, last, json.dumps(held)))
                    key = event.get("key")
                    if isinstance(key, str) and len(key) <= 32:
                        if event.get("down"):
                            if len(held) < 256 or key in held:
                                held[key] = str(event.get("who", ""))[:80]
                        else:
                            held.pop(key, None)
                    self.scanned = offset + len(line)
                progress = {"end": self.scanned, "last": last, "held": held, "header": signature}
                db.execute("INSERT OR REPLACE INTO metadata VALUES (1,?)", (json.dumps(progress),))
            db.commit()
        except Exception as exc:
            self.error = str(exc)
        finally:
            if db:
                db.close()
            if acquired:
                INDEX_LOCK.release()
            self.source.close()
            self.done.set()

    def locate(self, when):
        if self.error:
            raise ValueError(self.error)
        with closing(sqlite3.connect(self.path, timeout=.1)) as db:
            first = db.execute("SELECT off,t,held FROM frames WHERE off<? ORDER BY off LIMIT 1",
                               (self.total,)).fetchone()
            if first is None:
                raise ValueError("recording has no complete frame")
            row = db.execute("SELECT off,t,held FROM frames WHERE t<=? AND off<? "
                             "ORDER BY t DESC,off DESC LIMIT 1", (when, self.total)).fetchone() or first
        return {"start": row[0], "at": row[1], "held": json.loads(row[2]), "origin": first[1]}

    def close(self):
        # The worker owns a duplicate fd and closes it itself. Cancellation
        # never closes a descriptor while its indexing thread is reading it.
        self.cancelled.set()
