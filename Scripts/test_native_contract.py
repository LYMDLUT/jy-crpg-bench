#!/usr/bin/env python3
"""Run native contract regressions without launching the app or DOS core.

Compile the current Swift declarations at test time: command-line parsing,
Request/bounded, and the complete /screen branch plus its response helpers.
Only the emulator, core metadata, and log are test doubles. This checks Swift
behavior and argument propagation, not real-network or framebuffer rendering.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def declaration(source: str, signature: str) -> str:
    """Extract a declaration using the source's matching closing indentation."""
    opening = re.search(r"(?m)^([ \t]*)" + re.escape(signature), source)
    if opening is None:
        raise AssertionError(f"Swift declaration missing: {signature}")
    closing = re.search(r"(?m)^" + opening[1] + r"\}$", source[opening.end():])
    if closing is None:
        raise AssertionError(f"Swift declaration unterminated: {signature}")
    return source[opening.start():opening.end() + closing.end()]


def fixture_source() -> str:
    app = (ROOT / "Sources/QunXia/App.swift").read_text(encoding="utf-8")
    api = (ROOT / "Sources/QunXia/ControlAPI.swift").read_text(encoding="utf-8")
    path = declaration(app, "static func gamePath(root: URL)")
    overrides = declaration(app, "static func applyOptionOverrides(log: ActionLog)")
    handle = declaration(api, "private func handle(_ r: Request) -> Data")
    switch = handle.index("switch (r.method, Self.route(r.path)) {")
    prefix = handle[:handle.index("{", switch) + 1]
    start = handle.index('        case ("GET", "/screen"):')
    end = handle.index("\n        case ", start + 1)
    # Keep the production setup, switch and complete /screen branch verbatim.
    # Other routes are unnecessary for this fixture and need the actual core.
    screen_handle = prefix + "\n" + handle[start:end] + '''
        default: fatalError("unexpected fixture route")
        }
    }
'''
    helpers = "\n".join(declaration(api, signature) for signature in (
        "private struct Request",
        "private func bounded(_ r: Request, _ key: String, default fallback: Int,",
        "private static func route(_ path: String) -> String",
        "private func reply(_ r: Request, ok: Bool, status: Int = 200, extra: [String: Any],",
        "private func json(_ obj: Any) -> Data",
        "private func respond(_ status: Int, _ ctype: String, _ payload: Data) -> Data",
    ))
    return '''import Foundation
import CoreFoundation

var options: [String: String] = [:]
func core_set_option(_ key: String, _ value: String) { options[key] = value }
func core_width() -> Int { 320 }
func core_height() -> Int { 200 }
func core_frame_serial() -> Int { 1 }
func core_frame_hash() -> UInt64 { 1 }
final class ActionLog {
    func add(_ verb: String, _ target: String, payload: String = "",
             image: Data? = nil, ok: Bool = true) {}
}
final class Emulator {
    struct Shot {
        let scale: Int
        var width: Int { 320 * scale }
        var height: Int { 200 * scale }
        var png: Data { Data("fixture-scale-\\(scale)".utf8) }
    }
    var calls: [Int] = []
    func snapshot(scale: Int) -> Shot? {
        calls.append(scale)
        return Shot(scale: scale)
    }
}
func emit(_ object: Any) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    FileHandle.standardOutput.write(data + Data("\\n".utf8))
}
enum Paths {
''' + path + "\n" + overrides + '''
}
final class API {
    let emu = Emulator()
    let log = ActionLog()
''' + helpers + "\n" + screen_handle + '''
    func run(_ mode: String) {
        let data = FileHandle.standardInput.readDataToEndOfFile()
        guard let request = Request(data) else { fatalError("fixture request did not parse") }
        if mode == "int" {
            let value = bounded(request, "times", default: 1, min: 0, max: 100)
            emit(["value": value.map { $0 as Any } ?? NSNull()])
        } else {
            let response = handle(request)
            let separator = response.range(of: Data("\\r\\n\\r\\n".utf8))!
            let header = String(data: response[..<separator.lowerBound], encoding: .utf8)!
            let body = response[separator.upperBound...]
            let json = (try? JSONSerialization.jsonObject(with: Data(body))) ?? NSNull()
            emit(["calls": emu.calls, "header": header, "json": json,
                  "body": String(data: body, encoding: .utf8) ?? ""])
        }
    }
}
let mode = ProcessInfo.processInfo.environment["NATIVE_TEST_MODE"]!
if mode == "path" {
    let root = URL(fileURLWithPath: ProcessInfo.processInfo.environment["NATIVE_TEST_ROOT"]!)
    Paths.applyOptionOverrides(log: ActionLog())
    emit(["path": Paths.gamePath(root: root).path, "options": options])
} else {
    API().run(mode)
}
'''


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"),
                     "native contract regressions require macOS and swiftc")
class NativeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = tempfile.TemporaryDirectory(prefix="qunxia-native-contract-")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.tmp = Path(cls.workspace.name).resolve()
        source = cls.tmp / "fixture.swift"
        source.write_text(fixture_source(), encoding="utf-8")
        cls.exe = cls.tmp / "fixture"
        result = subprocess.run(["swiftc", "-O", str(source), "-o", str(cls.exe)],
                                text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(f"swiftc failed:\n{result.stdout}\n{result.stderr}")

    def invoke(self, mode: str, *args: str, request: str = "", root: Path | None = None) -> dict:
        env = dict(os.environ, NATIVE_TEST_MODE=mode)
        env.pop("QUNXIA_SET", None)
        if root is not None:
            env["NATIVE_TEST_ROOT"] = str(root)
        result = subprocess.run([str(self.exe), *args], env=env, input=request,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_game_path_skips_set_values_and_keeps_explicit_game(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.tmp) as raw:
            root = Path(raw)
            game = root / "game"
            game.mkdir()
            play = game / "PLAY.BAT"
            play.write_text("@echo off\n", encoding="utf-8")
            explicit = root / "custom game.rom"
            explicit.write_bytes(b"fixture")
            cases = [
                ([], play, {}),
                (["--set", "dosbox_pure_cycles=77000"], play, {"dosbox_pure_cycles": "77000"}),
                (["--port", "9000", "--set", "a=b"], play, {"a": "b"}),
                (["--set", "a=b", "--port", "9000"], play, {"a": "b"}),
                (["--set", "a=b", "--set", "c=d"], play, {"a": "b", "c": "d"}),
                (["--set", "a=b", str(explicit)], explicit, {"a": "b"}),
                ([str(explicit), "--set", "a=b"], explicit, {"a": "b"}),
                (["--set", "a=b", "--port", "9000", "--set", "c=d", str(explicit)],
                 explicit, {"a": "b", "c": "d"}),
                (["--set"], play, {}),
            ]
            for args, expected, options in cases:
                with self.subTest(args=args):
                    result = self.invoke("path", *args, root=root)
                    self.assertEqual(result, {"path": str(expected), "options": options})
            play.unlink()
            self.assertEqual(self.invoke("path", "--set", "a=b", root=root)["path"], str(game))

    def test_request_integer_boundaries_do_not_trap(self) -> None:
        cases = [
            ("0", 0), ("1", 1), ("100", 100), ("101", None), ("-1", None),
            ("true", None), ("false", None), ("1.5", None), ("1e2", 100),
            ("9223372036854775807", None), ("9223372036854775808", None),
            ("-9223372036854775808", None), ("-9223372036854775809", None),
            ("1e100", None), ("-1e100", None),
        ]
        for number, expected in cases:
            with self.subTest(number=number):
                body = '{"times":' + number + '}'
                request = f"POST /key HTTP/1.1\r\nContent-Length: {len(body)}\r\n\r\n{body}"
                self.assertEqual(self.invoke("int", request=request)["value"], expected)
        for value, expected in (("1", 1), ("0", 0), ("9223372036854775807", None),
                                ("9223372036854775808", None), ("1.5", None)):
            with self.subTest(query=value):
                request = f"POST /key?times={value} HTTP/1.1\r\n\r\n"
                self.assertEqual(self.invoke("int", request=request)["value"], expected)
        self.assertEqual(self.invoke("int", request="POST /key HTTP/1.1\r\n\r\n")["value"], 1)

    def test_screen_passes_normalized_scale_and_reports_the_returned_shot(self) -> None:
        for value, expected in ((None, 2), ("1", 1), ("2", 2), ("6", 6), ("99", 6),
                                ("0", 1), ("-3", 1), ("invalid", 2)):
            for path in ("/screen", "/api/screen"):
                with self.subTest(value=value, path=path):
                    query = "" if value is None else f"?scale={value}"
                    request = f"GET {path}{query} HTTP/1.1\r\n\r\n"
                    result = self.invoke("screen", request=request)
                    self.assertEqual(result["calls"], [expected])
                    self.assertTrue(result["header"].startswith("HTTP/1.1 200"))
                    self.assertEqual(result["json"]["scale"], expected)
                    self.assertEqual(result["json"]["image_width"], 320 * expected)
                    self.assertEqual(result["json"]["image_height"], 200 * expected)

    def test_screen_raw_png_uses_scale_and_invalid_format_skips_capture(self) -> None:
        for target, headers in (("/screen?scale=3&format=png", ""),
                                ("/screen?scale=3", "Accept: image/png\r\n")):
            with self.subTest(target=target, headers=headers):
                request = f"GET {target} HTTP/1.1\r\n{headers}\r\n"
                result = self.invoke("screen", request=request)
                self.assertEqual(result["calls"], [3])
                self.assertIn("Content-Type: image/png", result["header"])
                self.assertEqual(result["body"], "fixture-scale-3")
        result = self.invoke("screen", request="GET /screen?format=jpeg HTTP/1.1\r\n\r\n")
        self.assertEqual(result["calls"], [])
        self.assertTrue(result["header"].startswith("HTTP/1.1 400"))


if __name__ == "__main__":
    unittest.main()
