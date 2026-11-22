"""Invoices saved as JSON files."""

import json
from dataclasses import asdict
from pathlib import Path

from invoices.model import Invoice, Line


def save(invoice: Invoice, folder: Path) -> Path:
    path = Path(folder) / f"{invoice.number}.json"
    path.write_text(json.dumps(asdict(invoice), indent=2))
    return path


def load(path: Path) -> Invoice:
    data = json.loads(Path(path).read_text())
    lines = [Line(**line) for line in data.pop("lines")]
    return Invoice(**data, lines=lines)
