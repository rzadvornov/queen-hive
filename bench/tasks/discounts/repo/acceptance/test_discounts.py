"""Acceptance tests written by the product owner. Do not change."""
import unittest

from shop.cart import Cart


def cart(**items):
    c = Cart()
    for item, n in items.items():
        c.add(item, n)
    return c


class Discounts(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(cart(tea=2).total(), 500)

    def test_combo_half_price_croissant(self):
        self.assertEqual(cart(coffee=1, croissant=1).total(), 350 + 140)

    def test_combo_per_coffee(self):
        self.assertEqual(cart(coffee=1, croissant=2).total(), 350 + 140 + 280)
        self.assertEqual(cart(coffee=2, croissant=3).total(), 700 + 140 * 2 + 280)

    def test_croissant_alone(self):
        self.assertEqual(cart(croissant=2).total(), 560)

    def test_muffins_buy_three_pay_two(self):
        self.assertEqual(cart(muffin=3).total(), 600)
        self.assertEqual(cart(muffin=4).total(), 900)
        self.assertEqual(cart(muffin=6).total(), 1200)

    def test_both_rules(self):
        self.assertEqual(cart(coffee=1, croissant=1, muffin=3).total(), 350 + 140 + 600)

    def test_existing_api(self):
        c = cart(coffee=1, croissant=1)
        self.assertEqual(c.subtotal(), 630)


if __name__ == "__main__":
    unittest.main()
