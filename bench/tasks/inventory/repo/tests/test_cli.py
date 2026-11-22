import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from inventory.cli import main


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.environ["INVENTORY_FILE"] = os.path.join(self.dir.name, "inv.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_add_and_list(self):
        main(["add", "B2", "bolt", "10", "0.25"])
        main(["add", "A1", "nut", "5", "0.10"])
        out = io.StringIO()
        with redirect_stdout(out):
            main(["list"])
        self.assertEqual(out.getvalue().splitlines(), ["A1\tnut\t5\t0.10", "B2\tbolt\t10\t0.25"])
