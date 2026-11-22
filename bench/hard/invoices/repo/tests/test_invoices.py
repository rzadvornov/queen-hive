import tempfile
import unittest
from pathlib import Path

from invoices.model import Invoice
from invoices.render import render
from invoices.store import load, save


class Invoices(unittest.TestCase):
    def invoice(self):
        inv = Invoice("2026-001", "Ann", vat_rate=0.2)
        inv.add("Widget", 3, 1999)
        inv.add("Gadget", 1, 12550)
        return inv

    def test_totals(self):
        inv = self.invoice()
        self.assertEqual((inv.subtotal_cents(), inv.vat_cents(), inv.total_cents()), (18547, 3709, 22256))

    def test_render(self):
        text = render(self.invoice())
        self.assertIn("$222.56", text.splitlines()[-1])

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load(save(self.invoice(), Path(tmp))), self.invoice())
