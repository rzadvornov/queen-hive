"""Hidden tests: the report is fast and its output is byte-identical to the original's."""
import csv
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from bench_data import orders  # noqa: E402
from reference_report import customer_report as reference  # noqa: E402

from sales.report import customer_report  # noqa: E402

BIG_SHA256 = "498dc2e4239ce2ae4740d47880661293e3e404184bd7f66c404a56dbf3ecf034"


class Report(unittest.TestCase):
    def test_identical_small(self):
        for seed in range(3):
            data = orders(3000, 300, seed)
            self.assertEqual(customer_report(data), reference(data))

    def test_ties_keep_first_appearance(self):
        data = [("x", 1.0), ("y", 2.0), ("z", 1.0), ("w", 2.0)]
        self.assertEqual(customer_report(data), reference(data))

    def test_float_sums_identical(self):
        data = [("a", 0.1)] * 10 + [("b", 1e16), ("b", 1.0), ("b", -1e16)]
        self.assertEqual(customer_report(data), reference(data))

    def test_fast_and_identical_on_full_export(self):
        data = orders(200_000, 3000, 42)
        started = time.perf_counter()
        text = customer_report(data)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), BIG_SHA256)

    def test_cli_same_output(self):
        data = orders(2000, 100, 7)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "orders.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["customer", "amount"])
                writer.writerows(data)
            out = subprocess.run([sys.executable, "-m", "sales", "report", path], capture_output=True, text=True,
                                 check=True).stdout
        self.assertEqual(out, reference(data))
