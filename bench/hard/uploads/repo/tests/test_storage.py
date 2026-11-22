import tempfile
import unittest
from pathlib import Path

from files.storage import Storage
from files.web import handle_upload


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "store")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_read(self):
        self.storage.save("a.txt", b"hi")
        self.assertEqual(self.storage.read("a.txt"), b"hi")

    def test_subfolder(self):
        self.assertEqual(handle_upload(self.storage, "docs/2026/report.pdf", b"x")[0], 201)

    def test_dotdot_rejected(self):
        self.assertEqual(handle_upload(self.storage, "../evil.txt", b"x")[0], 400)
