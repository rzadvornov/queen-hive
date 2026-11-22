import unittest

from reports.data import Report, Row
from reports.render import render

REPORT = Report("Q3", [Row("North", 10, 100.0), Row("South", 5, 250.5)])


class Render(unittest.TestCase):
    def test_text(self):
        self.assertEqual(render(REPORT, "text").splitlines()[2].split(), ["South", "5", "250.50"])

    def test_html(self):
        self.assertIn("<th>TOTAL</th><th>15</th><th>350.50</th>", render(REPORT, "html"))

    def test_unknown(self):
        with self.assertRaises(ValueError):
            render(REPORT, "pdf")
