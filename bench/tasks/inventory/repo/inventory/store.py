"""The inventory file: a JSON object of sku → item."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Item:
    sku: str
    name: str
    quantity: int
    price: float


def path() -> Path:
    return Path(os.environ.get("INVENTORY_FILE", "inventory.json"))


def load() -> dict[str, Item]:
    try:
        raw = json.loads(path().read_text())
    except FileNotFoundError:
        return {}
    return {sku: Item(**data) for sku, data in raw.items()}


def save(items: dict[str, Item]) -> None:
    path().write_text(json.dumps({sku: asdict(item) for sku, item in items.items()}, indent=2))
