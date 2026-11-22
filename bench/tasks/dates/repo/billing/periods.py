"""Billing periods: when a subscription renews."""

import datetime as dt


def next_billing_date(start: dt.date, months: int = 1) -> dt.date:
    """The renewal date `months` months after `start`."""
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    return start.replace(year=year, month=month)


def schedule(start: dt.date, count: int) -> list[dt.date]:
    """The next `count` renewal dates, each counted from the start date."""
    return [next_billing_date(start, n) for n in range(1, count + 1)]
