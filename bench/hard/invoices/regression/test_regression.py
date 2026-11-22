"""Hidden regression tests: USD invoices are exactly as before."""
import json
import tempfile
import unittest
from pathlib import Path

from invoices.model import Invoice
from invoices.render import render
from invoices.store import load

OLD_JSON = {"number": "2025-077", "customer": "Bob", "vat_rate": 0.19,
            "lines": [{"description": "Plan", "quantity": 12, "unit_cents": 4999}]}

EXPECTED = """Invoice 2025-077 for Bob

Plan                            12 x       $49.99 =      $599.88

Subtotal                                                 $599.88
VAT                                                      $113.98
Total                                                    $713.86"""


class Regression(unittest.TestCase):
    def test_old_invoice_loads_and_renders_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps(OLD_JSON))
            invoice = load(path)
        self.assertEqual(render(invoice), EXPECTED)
        self.assertEqual(invoice.total_cents(), 71386)

    def test_default_is_usd(self):
        inv = Invoice("1", "C")
        inv.add("x", 2, 150)
        self.assertEqual(inv.total_cents(), 300)
        self.assertIn("$3.00", render(inv))
