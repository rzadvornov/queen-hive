"""Hidden tests: the shop's local day follows Berlin time, daylight saving included."""
import datetime as dt
import unittest

from ledger.ingest import ingest
from ledger.reports import monthly_totals

D = dt.date


def day(time):
    return ingest([{"id": "x", "time": time, "amount_cents": 1}])[0].business_day


class BerlinTime(unittest.TestCase):
    def test_summer_month_end(self):
        self.assertEqual(day("2026-07-31T22:30:00Z"), D(2026, 8, 1))      # 00:30 CEST

    def test_summer_before_midnight(self):
        self.assertEqual(day("2026-06-30T21:59:00Z"), D(2026, 6, 30))     # 23:59 CEST

    def test_summer_month_totals(self):
        entries = ingest([{"id": "a", "time": "2026-08-31T22:15:00Z", "amount_cents": 900},
                          {"id": "b", "time": "2026-08-31T21:45:00Z", "amount_cents": 100}])
        self.assertEqual(monthly_totals(entries), {"2026-08": 100, "2026-09": 900})

    def test_spring_forward_day(self):
        self.assertEqual(day("2026-03-29T00:30:00Z"), D(2026, 3, 29))     # 01:30 CET, before the switch
        self.assertEqual(day("2026-03-29T22:30:00Z"), D(2026, 3, 30))     # 00:30 CEST

    def test_fall_back_day(self):
        self.assertEqual(day("2026-10-25T22:30:00Z"), D(2026, 10, 25))    # 23:30 CET
        self.assertEqual(day("2026-10-24T22:30:00Z"), D(2026, 10, 25))    # 00:30 CEST

    def test_winter_unchanged(self):
        self.assertEqual(day("2026-11-30T23:30:00Z"), D(2026, 12, 1))

    def test_other_offsets_in_input(self):
        self.assertEqual(day("2026-07-31T18:30:00-04:00"), D(2026, 8, 1))  # 22:30Z = 00:30 CEST
