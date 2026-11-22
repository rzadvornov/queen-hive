"""Invoices: lines priced in USD cents, VAT on the subtotal."""

from dataclasses import dataclass, field


@dataclass
class Line:
    description: str
    quantity: int
    unit_cents: int

    @property
    def amount_cents(self) -> int:
        return self.quantity * self.unit_cents


@dataclass
class Invoice:
    number: str
    customer: str
    vat_rate: float = 0.0
    lines: list[Line] = field(default_factory=list)

    def add(self, description: str, quantity: int, unit_cents: int) -> None:
        self.lines.append(Line(description, quantity, unit_cents))

    def subtotal_cents(self) -> int:
        return sum(line.amount_cents for line in self.lines)

    def vat_cents(self) -> int:
        return round(self.subtotal_cents() * self.vat_rate)

    def total_cents(self) -> int:
        return self.subtotal_cents() + self.vat_cents()
