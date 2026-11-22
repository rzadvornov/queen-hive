"""Hidden regression tests: existing behaviour."""
import unittest

from sales.report import customer_report


class Regression(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(customer_report([("ann", 10.0), ("bob", 30.0), ("ann", 5.5)]),
                         "1. bob: 30.00 (1 orders)\n2. ann: 15.50 (2 orders)\n")

    def test_empty(self):
        self.assertEqual(customer_report([]), "")

    def test_case_sensitive_names(self):
        self.assertEqual(customer_report([("acme", 1.0), ("Acme", 2.0)]), "1. Acme: 2.00 (1 orders)\n2. acme: 1.00 (1 orders)\n")

    def test_negative_totals(self):
        self.assertEqual(customer_report([("r", -5.0), ("s", 0.0)]), "1. s: 0.00 (1 orders)\n2. r: -5.00 (1 orders)\n")
