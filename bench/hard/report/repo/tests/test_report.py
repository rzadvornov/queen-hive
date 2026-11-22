import unittest

from sales.report import customer_report


class Report(unittest.TestCase):
    def test_ranking(self):
        orders = [("ann", 10.0), ("bob", 30.0), ("ann", 5.5)]
        self.assertEqual(customer_report(orders), "1. bob: 30.00 (1 orders)\n2. ann: 15.50 (2 orders)\n")

    def test_empty(self):
        self.assertEqual(customer_report([]), "")
