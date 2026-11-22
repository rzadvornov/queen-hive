"""Acceptance tests written by the product owner. Do not change."""
import datetime as dt
import unittest

from billing.invoice import invoice_for
from billing.periods import next_billing_date, schedule

D = dt.date


class MonthEnd(unittest.TestCase):
    def test_short_month(self):
        self.assertEqual(next_billing_date(D(2026, 1, 31)), D(2026, 2, 28))
        self.assertEqual(next_billing_date(D(2026, 3, 31)), D(2026, 4, 30))

    def test_leap_year(self):
        self.assertEqual(next_billing_date(D(2028, 1, 30)), D(2028, 2, 29))
        self.assertEqual(next_billing_date(D(2028, 2, 29), 12), D(2029, 2, 28))

    def test_schedule_keeps_the_day(self):
        self.assertEqual(schedule(D(2026, 1, 31), 3), [D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)])

    def test_normal_dates_unchanged(self):
        self.assertEqual(next_billing_date(D(2026, 5, 10), 2), D(2026, 7, 10))
        self.assertEqual(next_billing_date(D(2026, 11, 30), 3), D(2027, 2, 28))

    def test_invoice(self):
        self.assertEqual(invoice_for("ana", D(2026, 8, 31), 999).period_end, D(2026, 9, 30))


if __name__ == "__main__":
    unittest.main()
