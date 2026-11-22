"""Acceptance tests written by the product owner. Do not change."""
import unittest

from reports.data import Report, Row
from reports.render import render

REPORT = Report("Q3 sales", [Row("North", 10, 100.0), Row("South", 5, 250.5), Row("East", 7, 180.25)])

TEXT = """Q3 sales
========
South              5      250.50
East               7      180.25
North             10      100.00
TOTAL             22      530.75"""

HTML = ("<h1>Q3 sales</h1><table><tr><td>South</td><td>5</td><td>250.50</td></tr>"
        "<tr><td>East</td><td>7</td><td>180.25</td></tr><tr><td>North</td><td>10</td><td>100.00</td></tr>"
        "<tr><th>TOTAL</th><th>22</th><th>530.75</th></tr></table>")


class Markdown(unittest.TestCase):
    def test_markdown(self):
        lines = render(REPORT, "markdown").splitlines()
        self.assertTrue(lines[0].startswith("#") and "Q3 sales" in lines[0])
        table = [line for line in lines if line.startswith("|")]
        cells = [[c.strip() for c in line.strip("|").split("|")] for line in table]
        self.assertEqual(cells[0], ["Region", "Units", "Revenue"])
        self.assertTrue(set(table[1].replace("|", "").strip()) <= set("-: "))
        self.assertEqual([c[0] for c in cells[2:5]], ["South", "East", "North"])
        self.assertEqual(cells[2][1:], ["5", "250.50"])
        self.assertEqual(cells[5], ["**TOTAL**", "**22**", "**530.75**"])

    def test_existing_formats_unchanged(self):
        self.assertEqual(render(REPORT, "text"), TEXT)
        self.assertEqual(render(REPORT, "html"), HTML)

    def test_empty_report(self):
        empty = render(Report("Empty", []), "markdown")
        self.assertIn("**0**", empty)


if __name__ == "__main__":
    unittest.main()
