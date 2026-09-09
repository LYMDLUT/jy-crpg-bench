"""Seek the existing recording format while keeping pages and indexes bounded."""
import asyncio
import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from recording import RecordingAPI
from recording_store import RecordingStore


def frame(when, color, marked=True):
    payload = struct.pack("<BHHBBHHHH", 1, 1, 1, 1, 1, 1, 1, 1, 0) + bytes(color)
    event = {"t": when, "d": base64.b64encode(zlib.compress(payload)).decode()}
    if marked:
        event["k"] = 1
    return event


class ReplayIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qunxia-seek-")
        self.path = Path(self.temp.name) / "recording.jsonl"
        self.store = RecordingStore(self.path, started=100)
        for event in [frame(5, (255, 0, 0), marked=False),
                      {"t": 6, "key": "enter", "down": True, "who": "fixture"},
                      frame(7, (0, 255, 0)), {"t": 8, "key": "enter", "down": False},
                      frame(9, (0, 0, 255))]:
            self.assertTrue(self.store.append(event))
        self.api = RecordingAPI(self.store)
        app = web.Application()
        app.router.add_get("/api/recording", self.api.handle)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        indexes = [r.seek_index for r, _ in self.api.readers.values() if r.seek_index]
        self.api.close()
        for index in indexes:
            self.assertTrue(await asyncio.to_thread(index.done.wait, 3))
        await self.client.close()
        self.store.close()
        self.temp.cleanup()

    async def open(self):
        return await (await self.client.get("/api/recording?view=paged")).json()

    async def seek(self, token, when):
        for _ in range(100):
            response = await self.client.get("/api/recording", params={"view": "paged", "token": token, "time": when})
            data = await response.json()
            if response.status != 202:
                self.assertEqual(response.status, 200, data)
                return data
            self.assertLessEqual(data["scanned"], data["total"])
            await asyncio.sleep(.01)
        self.fail("seek index did not finish")

    async def test_start_and_bidirectional_seek_return_complete_frames_and_key_state(self):
        original = self.path.read_bytes()
        first = await self.open()
        reader = self.api.readers[first["token"]][0]
        self.assertIsNone(reader.seek_index, "ordinary playback does not start indexing")
        for when, expected, held in [(0, 5, {}), (9, 9, {}), (7.5, 7, {"enter": "fixture"}), (5, 5, {})]:
            data = await self.seek(first["token"], when)
            self.assertEqual(data["events"][0]["t"], expected)
            self.assertEqual(data["seek"]["held"], held)
            self.assertEqual(data["seek"]["origin"], 5)
        self.assertEqual(self.path.read_bytes(), original)

    async def test_reader_remains_pinned_across_append_and_reset(self):
        first = await self.open()
        self.store.append(frame(10, (20, 30, 40)))
        self.store.reset(200)
        self.store.append(frame(0, (100, 100, 100)))
        old = await self.seek(first["token"], 100)
        self.assertEqual(old["events"][0]["t"], 9)
        new = await self.open()
        fresh = await self.seek(new["token"], 0)
        self.assertEqual(fresh["events"][0]["t"], 0)

    async def test_invalid_seek_and_expired_token_are_rejected(self):
        first = await self.open()
        for when in ("nan", "inf", "-1", "bad"):
            response = await self.client.get("/api/recording", params={"view": "paged", "token": first["token"], "time": when})
            self.assertEqual(response.status, 400)
        await self.client.get("/api/recording", params={"view": "paged", "token": first["token"], "close": "1"})
        response = await self.client.get("/api/recording", params={"view": "paged", "token": first["token"], "time": 0})
        self.assertEqual(response.status, 410)

    async def test_truncated_keyframe_marker_is_not_an_index_anchor(self):
        broken = frame(0, (1, 2, 3))
        payload = zlib.decompress(base64.b64decode(broken["d"]))[:-2]
        broken["d"] = base64.b64encode(zlib.compress(payload)).decode()
        self.store.close()
        header, rest = self.path.read_bytes().split(b"\n", 1)
        self.path.write_bytes(header + b"\n" + json.dumps(broken).encode() + b"\n" + rest)
        self.store = RecordingStore(self.path)
        self.api.store = self.store
        first = await self.open()
        page = await self.seek(first["token"], 0)
        self.assertEqual(page["seek"]["origin"], 5)
        self.assertEqual(page["events"][0]["t"], 5)

    async def test_closing_an_indexing_reader_releases_its_duplicate_descriptor(self):
        from replay_index import INDEX_LOCK
        first = await self.open()
        reader = self.api.readers[first["token"]][0]
        with INDEX_LOCK:
            response = await self.client.get("/api/recording", params={"view": "paged", "token": first["token"], "time": 0})
            self.assertEqual(response.status, 202)
            index = reader.seek_index
            fd = index.source.fd
            await self.client.get("/api/recording", params={"view": "paged", "token": first["token"], "close": "1"})
        self.assertTrue(await asyncio.to_thread(index.done.wait, 3))
        with self.assertRaises(OSError):
            os.fstat(fd)

    async def test_large_event_history_stays_on_disk_and_seek_pages_remain_bounded(self):
        self.store.close()
        with self.path.open("ab") as stream:
            for n in range(100000):
                stream.write((json.dumps({"t": n + 10, "act": "GET", "label": "look"}) + "\n").encode())
            stream.write((json.dumps(frame(100010, (200, 200, 200))) + "\n").encode())
        self.store = RecordingStore(self.path)
        self.api.store = self.store
        first = await self.open()
        page = await self.seek(first["token"], 50000)
        self.assertLessEqual(len(page["events"]), 2048)
        self.assertLess(len(json.dumps(page)), 1 << 20)
        self.assertFalse(page["done"])
        import sqlite3
        index = self.api.readers[first["token"]][0].seek_index
        db = sqlite3.connect(index.path)
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM frames").fetchone()[0], 4)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
