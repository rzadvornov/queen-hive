"""Plain-text invoices."""

from invoices.model import Invoice


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def render(invoice: Invoice) -> str:
    out = [f"Invoice {invoice.number} for {invoice.customer}", ""]
    for line in invoice.lines:
        out.append(f"{line.description:<30}{line.quantity:>4} x {money(line.unit_cents):>12} = {money(line.amount_cents):>12}")
    out += ["", f"{'Subtotal':<52}{money(invoice.subtotal_cents()):>12}",
            f"{'VAT':<52}{money(invoice.vat_cents()):>12}",
            f"{'Total':<52}{money(invoice.total_cents()):>12}"]
    return "\n".join(out)
