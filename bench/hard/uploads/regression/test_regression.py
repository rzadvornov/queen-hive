"""Hidden regression tests: legitimate names keep working."""
import tempfile
import unittest
from pathlib import Path

from files.storage import Storage
from files.web import handle_upload


class Legit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "store"
        self.storage = Storage(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def ok(self, raw, expected):
        status, _ = handle_upload(self.storage, raw, b"data")
        self.assertEqual(status, 201, raw)
        self.assertEqual((self.root / expected).read_bytes(), b"data")

    def test_plain_and_nested(self):
        self.ok("a.txt", "a.txt")
        self.ok("docs/2026/q1.pdf", "docs/2026/q1.pdf")

    def test_dots_in_names(self):
        self.ok("..hidden", "..hidden")
        self.ok("v1..2.txt", "v1..2.txt")
        self.ok("notes/..draft.md", "notes/..draft.md")

    def test_encoded_and_unicode(self):
        self.ok("my%20file.txt", "my file.txt")
        self.ok("отчёт.pdf", "отчёт.pdf")

    def test_missing_name(self):
        self.assertEqual(handle_upload(self.storage, "", b"x")[0], 400)

    def test_read_back(self):
        self.storage.save("x/y.bin", b"\0\1")
        self.assertEqual(self.storage.read("x/y.bin"), b"\0\1")
