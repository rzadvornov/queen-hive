"""Acceptance tests written by the product owner. Do not change."""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest


def run(*args, env):
    return subprocess.run([sys.executable, "-m", "inventory", *args], capture_output=True, text=True, env=env, check=True)


class Export(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "INVENTORY_FILE": os.path.join(self.dir.name, "inv.json")}
        run("add", "B2", "bolt", "10", "0.25", env=self.env)
        run("add", "A1", "nut, hex", "5", "0.1", env=self.env)

    def tearDown(self):
        self.dir.cleanup()

    def test_json_stdout(self):
        data = json.loads(run("export", "--format", "json", env=self.env).stdout)
        self.assertEqual([d["sku"] for d in data], ["A1", "B2"])
        self.assertEqual(data[0], {"sku": "A1", "name": "nut, hex", "quantity": 5, "price": 0.1})

    def test_csv_stdout(self):
        rows = list(csv.DictReader(io.StringIO(run("export", "--format", "csv", env=self.env).stdout)))
        self.assertEqual([r["sku"] for r in rows], ["A1", "B2"])
        self.assertEqual(rows[0]["name"], "nut, hex")          # quoted properly
        self.assertEqual(set(rows[0]), {"sku", "name", "quantity", "price"})

    def test_out_file(self):
        out = os.path.join(self.dir.name, "export.json")
        result = run("export", "--format", "json", "--out", out, env=self.env)
        self.assertEqual(result.stdout.strip(), "")
        with open(out) as handle:
            self.assertEqual(len(json.load(handle)), 2)

    def test_bad_format(self):
        result = subprocess.run([sys.executable, "-m", "inventory", "export", "--format", "xml"],
                                capture_output=True, text=True, env=self.env)
        self.assertNotEqual(result.returncode, 0)

    def test_documented(self):
        with open("README.md") as handle:
            self.assertIn("export", handle.read())


if __name__ == "__main__":
    unittest.main()
