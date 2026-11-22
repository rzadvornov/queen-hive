"""Invoices for a subscription."""

import datetime as dt
from dataclasses import dataclass

from billing.periods import next_billing_date


@dataclass
class Invoice:
    customer: str
    period_start: dt.date
    period_end: dt.date
    amount_cents: int


def invoice_for(customer: str, start: dt.date, monthly_cents: int) -> Invoice:
    return Invoice(customer, start, next_billing_date(start), monthly_cents)
