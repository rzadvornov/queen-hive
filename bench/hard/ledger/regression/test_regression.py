"""Hidden regression tests: behaviour that already worked must keep working."""
import datetime as dt
import unittest

from ledger.ingest import ingest, parse_time
from ledger.reports import daily_totals, format_month, monthly_totals


def event(id, time, cents, type="payment"):
    return {"id": id, "time": time, "amount_cents": cents, "type": type}


class Regression(unittest.TestCase):
    def test_winter_days(self):
        days = [e.business_day for e in ingest([event("a", "2026-12-31T22:59:00Z", 1), event("b", "2026-12-31T23:00:00Z", 1)])]
        self.assertEqual(days, [dt.date(2026, 12, 31), dt.date(2027, 1, 1)])

    def test_offsets_in_input(self):
        day = ingest([event("a", "2026-02-01T00:30:00+01:00", 1)])[0].business_day
        self.assertEqual(day, dt.date(2026, 2, 1))

    def test_no_offset_rejected(self):
        with self.assertRaises(ValueError):
            parse_time("2026-02-01T00:30:00")

    def test_duplicates_refunds_and_months(self):
        entries = ingest([event("a", "2026-03-02T10:00:00Z", 500), event("a", "2026-03-02T10:00:00Z", 500),
                          event("b", "2026-04-02T10:00:00Z", 200, "refund")])
        self.assertEqual(monthly_totals(entries), {"2026-03": 500, "2026-04": -200})
        self.assertEqual(list(daily_totals(entries)), [dt.date(2026, 3, 2), dt.date(2026, 4, 2)])

    def test_format(self):
        self.assertEqual(format_month({"2026-01": -5, "2026-02": 100}), "2026-01         -0.05\n2026-02          1.00")
