"""Deterministic order data for the hidden tests."""
import random


def orders(n, customers, seed):
    rng = random.Random(seed)
    names = [f"Customer {i:05d}" for i in range(customers)] + ["acme", "Acme", "Zoë GmbH", "株式会社テスト"]
    out = []
    for _ in range(n):
        amount = round(rng.uniform(-50, 500), 2) if rng.random() < 0.97 else round(rng.uniform(-500, -1), 2)
        out.append((rng.choice(names), amount))
    out += [("tie-b", 100.0), ("tie-a", 100.0), ("tie-c", 99.995), ("tie-d", 100.005)]
    return out
