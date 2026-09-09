"""Real native serialization and filesystem failures, without game assets."""
import ctypes
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("cc"), "C compiler required")
class AtomicSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qunxia-atomic-save-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = pathlib.Path(cls.temp.name)
        shared = "-dynamiclib" if sys.platform == "darwin" else "-shared"
        common = ["cc", "-std=c11", "-O2", "-fPIC", "-pthread",
                  "-I" + str(ROOT / "Sources/CoreHost/include")]
        cls.core = cls.directory / "core.so"
        cls.host = cls.directory / "host.so"
        subprocess.run(common + [shared, str(ROOT / "server/test_fixtures/thread_probe_core.c"),
                                 "-o", str(cls.core)], check=True)
        obj = cls.directory / "host.o"
        hooks = [f"-D{name}=save_test_{name}" for name in
                 ("fwrite", "fflush", "fsync", "fclose", "rename")]
        subprocess.run(common + hooks + ["-c", str(ROOT / "Sources/CoreHost/CoreHost.c"),
                                        "-o", str(obj)], check=True)
        subprocess.run(common + [shared, str(obj),
                                 str(ROOT / "server/test_fixtures/save_io_faults.c"),
                                 "-o", str(cls.host)]
                       + ([] if sys.platform == "darwin" else ["-ldl"]), check=True)
        cls.lib = ctypes.CDLL(str(cls.host))
        cls.probe = ctypes.CDLL(str(cls.core))
        cls.lib.core_init.argtypes = [ctypes.c_char_p] * 3
        cls.lib.core_init.restype = ctypes.c_bool
        for name in ("core_save_state", "core_load_state"):
            getattr(cls.lib, name).argtypes = [ctypes.c_char_p]
            getattr(cls.lib, name).restype = ctypes.c_bool

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(self.folder.cleanup)
        self.path = pathlib.Path(self.folder.name) / "live.state"
        self.path.write_bytes(b"previous checkpoint")
        self.lib.save_io_failure(0)
        self.probe.probe_reset()
        self.assertTrue(self.lib.core_init(str(self.core).encode(), b"unused",
                                          self.folder.name.encode()))
        self.addCleanup(self.lib.core_shutdown)

    def assert_unchanged(self):
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_write_flush_sync_close_and_rename_failures_preserve_old_save(self):
        for mode in range(1, 6):
            with self.subTest(failure=mode):
                self.lib.save_io_failure(mode)
                self.assertFalse(self.lib.core_save_state(str(self.path).encode()))
                self.assert_unchanged()

    def test_failed_serialization_preserves_old_save(self):
        self.probe.probe_fail_serialize(1)
        self.assertFalse(self.lib.core_save_state(str(self.path).encode()))
        self.assert_unchanged()

    def test_success_replaces_the_file_and_can_be_loaded(self):
        self.assertTrue(self.lib.core_save_state(str(self.path).encode()))
        self.assertEqual(self.path.read_bytes(), b"{" + bytes(15))
        self.assertTrue(self.lib.core_load_state(str(self.path).encode()))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_filesize_limit_leaves_previous_save_intact(self):
        # The limit and SIGXFSZ disposition belong only to this child. This
        # exercises an actual failed OS write/flush, not a mocked C return.
        child = subprocess.run([sys.executable, "-c", """
import ctypes, json, resource, signal, sys
host, core, path = sys.argv[1:]
lib = ctypes.CDLL(host)
probe = ctypes.CDLL(core)
lib.core_init.argtypes = [ctypes.c_char_p] * 3
lib.core_init.restype = ctypes.c_bool
lib.core_save_state.argtypes = [ctypes.c_char_p]
lib.core_save_state.restype = ctypes.c_bool
probe.probe_reset()
assert lib.core_init(core.encode(), b'unused', b'/tmp')
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (8, 8))
print(json.dumps({'saved': bool(lib.core_save_state(path.encode()))}))
lib.core_shutdown()
""", str(self.host), str(self.core), str(self.path)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertFalse(json.loads(child.stdout)["saved"])
        self.assert_unchanged()


if __name__ == "__main__":
    unittest.main()
