import datetime as dt
import unittest

from ledger.ingest import ingest
from ledger.reports import format_month, monthly_totals


def event(id, time, cents, type="payment"):
    return {"id": id, "time": time, "amount_cents": cents, "type": type}


class Ledger(unittest.TestCase):
    def test_business_day_winter(self):
        entries = ingest([event("a", "2026-01-31T22:30:00Z", 1000)])   # 23:30 in Berlin
        self.assertEqual(entries[0].business_day, dt.date(2026, 1, 31))

    def test_duplicates_and_refunds(self):
        entries = ingest([event("a", "2026-02-10T10:00:00Z", 1000), event("a", "2026-02-10T10:00:00Z", 1000),
                          event("r", "2026-02-11T10:00:00Z", 300, "refund")])
        self.assertEqual(monthly_totals(entries), {"2026-02": 700})

    def test_format(self):
        self.assertEqual(format_month({"2026-02": 123456}), "2026-02      1,234.56")
