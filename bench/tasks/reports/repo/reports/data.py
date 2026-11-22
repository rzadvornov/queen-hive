"""Sales data: one row per region."""

from dataclasses import dataclass


@dataclass
class Row:
    region: str
    units: int
    revenue: float


@dataclass
class Report:
    title: str
    rows: list[Row]
