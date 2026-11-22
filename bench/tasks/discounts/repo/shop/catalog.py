"""Product catalog: prices in cents."""

PRICES = {
    "coffee": 350,
    "croissant": 280,
    "muffin": 300,
    "tea": 250,
}


def price_of(item: str) -> int:
    try:
        return PRICES[item]
    except KeyError:
        raise ValueError(f"unknown item: {item}") from None
