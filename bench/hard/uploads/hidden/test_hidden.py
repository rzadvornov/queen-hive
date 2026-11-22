"""Hidden tests: no upload may land outside the storage folder."""
import os
import tempfile
import unittest
from pathlib import Path

from files.storage import Storage
from files.web import handle_upload


class Escape(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "store"
        self.storage = Storage(self.root)
        (self.base / "outside").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def rejected(self, raw):
        before = {p for p in self.base.rglob("*")}
        status, _ = handle_upload(self.storage, raw, b"pwned")
        escaped = [p for p in self.base.rglob("*") if p not in before and self.root not in p.parents and p != self.root]
        self.assertEqual(escaped, [], f"{raw} wrote outside the storage folder")
        self.assertEqual(status, 400, raw)

    def test_dotdot_nested(self):
        self.rejected("a/../../outside/x.txt")

    def test_encoded_dotdot(self):
        self.rejected("%2e%2e/outside/x.txt")
        self.rejected("..%2foutside%2fx.txt")

    def test_absolute(self):
        self.rejected(str(self.base / "outside" / "abs.txt"))
        self.rejected("%2F" + str(self.base / "outside" / "abs2.txt").lstrip("/"))

    def test_symlink_inside_store(self):
        os.symlink(self.base / "outside", self.root / "link")
        self.rejected("link/x.txt")

    def test_null_byte(self):
        status, _ = handle_upload(self.storage, "a.txt%00.png", b"x")
        self.assertEqual(status, 400)

    def test_read_cannot_escape(self):
        (self.base / "outside" / "secret.txt").write_text("s")
        with self.assertRaises(ValueError):
            self.storage.read("../outside/secret.txt")
        with self.assertRaises(ValueError):
            self.storage.read(str(self.base / "outside" / "secret.txt"))
