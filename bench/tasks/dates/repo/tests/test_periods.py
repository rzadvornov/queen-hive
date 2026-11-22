import datetime as dt
import unittest

from billing.periods import next_billing_date, schedule


class Periods(unittest.TestCase):
    def test_mid_month(self):
        self.assertEqual(next_billing_date(dt.date(2026, 3, 15)), dt.date(2026, 4, 15))

    def test_year_end(self):
        self.assertEqual(next_billing_date(dt.date(2026, 12, 10)), dt.date(2027, 1, 10))

    def test_schedule(self):
        self.assertEqual(schedule(dt.date(2026, 1, 5), 2), [dt.date(2026, 2, 5), dt.date(2026, 3, 5)])
