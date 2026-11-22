"""Turns raw payment events into ledger entries on the shop's business day."""

import datetime as dt
from dataclasses import dataclass

SHOP_UTC_OFFSET = dt.timedelta(hours=1)   # Berlin


@dataclass(frozen=True)
class Entry:
    event_id: str
    business_day: dt.date
    amount_cents: int


def parse_time(raw: str) -> dt.datetime:
    """An ISO-8601 timestamp with an offset, as UTC."""
    when = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError(f"timestamp without an offset: {raw}")
    return when.astimezone(dt.timezone.utc)


def business_day(when_utc: dt.datetime) -> dt.date:
    """The shop's local calendar day of a moment."""
    return (when_utc + SHOP_UTC_OFFSET).date()


def ingest(events: list[dict]) -> list[Entry]:
    entries = []
    seen = set()
    for event in events:
        if event["id"] in seen:
            continue   # payment providers retry webhooks
        seen.add(event["id"])
        amount = int(event["amount_cents"])
        if event.get("type") == "refund":
            amount = -amount
        entries.append(Entry(event["id"], business_day(parse_time(event["time"])), amount))
    return entries
