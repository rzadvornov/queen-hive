import unittest

from shop.cart import Cart


class CartTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(Cart().total(), 0)

    def test_sum(self):
        cart = Cart()
        cart.add("coffee")
        cart.add("tea", 2)
        self.assertEqual(cart.total(), 350 + 2 * 250)

    def test_unknown_item(self):
        with self.assertRaises(ValueError):
            Cart().add("bagel")
