"""Revenue reports by day and by month."""

import datetime as dt
from collections import defaultdict

from ledger.ingest import Entry


def daily_totals(entries: list[Entry]) -> dict[dt.date, int]:
    totals: dict[dt.date, int] = defaultdict(int)
    for entry in entries:
        totals[entry.business_day] += entry.amount_cents
    return dict(sorted(totals.items()))


def monthly_totals(entries: list[Entry]) -> dict[str, int]:
    """Totals per month, keyed 'YYYY-MM'."""
    totals: dict[str, int] = defaultdict(int)
    for day, cents in daily_totals(entries).items():
        totals[f"{day.year:04d}-{day.month:02d}"] += cents
    return dict(sorted(totals.items()))


def format_month(totals: dict[str, int]) -> str:
    return "\n".join(f"{month}  {cents / 100:>12,.2f}" for month, cents in totals.items())
