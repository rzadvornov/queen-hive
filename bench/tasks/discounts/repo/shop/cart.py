"""A shopping cart and its total."""

from collections import Counter

from shop.catalog import price_of


class Cart:
    def __init__(self):
        self.items = Counter()

    def add(self, item: str, quantity: int = 1) -> None:
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        price_of(item)   # validates the item
        self.items[item] += quantity

    def subtotal(self) -> int:
        return sum(price_of(item) * n for item, n in self.items.items())

    def total(self) -> int:
        """The amount to pay, in cents."""
        return self.subtotal()
