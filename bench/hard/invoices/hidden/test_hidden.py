"""Hidden tests: other currencies, totals that add up, old invoices."""
import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path

from invoices import model, render as render_mod, store


def make(currency, vat=0.2, lines=(("Widget", 3, 1999), ("Gadget", 1, 12550), ("Cable", 7, 333))):
    """An invoice in a currency, whichever way the implementation takes it (constructor keyword)."""
    inv = model.Invoice("2026-009", "Eva", vat_rate=vat, currency=currency)
    for line in lines:
        inv.add(*line)
    return inv


SYMBOLS = {"EUR": "€", "GBP": "£", "JPY": "¥", "USD": "$"}
NUMBER = r"-?[\d,]+(?:\.\d+)?"


def amounts(text, symbol):
    """Every amount printed after `symbol`, as a number."""
    return [float(x.replace(",", "")) for x in re.findall(re.escape(symbol) + "(" + NUMBER + ")", text)]


class Currencies(unittest.TestCase):
    def test_symbols(self):
        for code, symbol in SYMBOLS.items():
            text = render_mod.render(make(code))
            self.assertIn(symbol, text, code)
            if code != "USD":
                self.assertNotIn("$", text, code)

    def test_eur_is_converted(self):
        text = render_mod.render(make("EUR"))
        total = amounts(text.splitlines()[-1], "€")[0]
        usd_total = make("USD").total_cents() / 100
        self.assertAlmostEqual(total, usd_total * 0.9137, delta=0.05)

    def test_total_equals_printed_lines(self):
        for code in ("EUR", "GBP", "JPY", "USD"):
            text = render_mod.render(make(code, lines=[("A", 3, 1999), ("B", 7, 333), ("C", 1, 1), ("D", 13, 777)]))
            lines = text.splitlines()
            item_amounts = [amounts(l, SYMBOLS[code])[-1] for l in lines if " x " in l]
            subtotal, vat, total = (amounts(l, SYMBOLS[code])[-1] for l in lines[-3:])
            self.assertAlmostEqual(sum(item_amounts), subtotal, places=6, msg=code)
            self.assertAlmostEqual(subtotal + vat, total, places=6, msg=code)

    def test_jpy_has_no_decimals(self):
        text = render_mod.render(make("JPY"))
        for value in re.findall("¥(" + NUMBER + ")", text):
            self.assertNotIn(".", value)

    def test_save_and_load_keep_currency(self):
        with tempfile.TemporaryDirectory() as tmp:
            again = store.load(store.save(make("GBP"), Path(tmp)))
        self.assertEqual(render_mod.render(again), render_mod.render(make("GBP")))

    def test_old_invoice_is_usd(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps({"number": "1", "customer": "B", "vat_rate": 0.0,
                                        "lines": [{"description": "x", "quantity": 1, "unit_cents": 500}]}))
            self.assertIn("$5.00", render_mod.render(store.load(path)))

    def test_unknown_currency_rejected(self):
        with self.assertRaises((ValueError, KeyError)):
            render_mod.render(make("XYZ"))
