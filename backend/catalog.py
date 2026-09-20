from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "catalog.csv"
IMAGE_PATH = "/assets/editorial-outfit-triptych.png"


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def load_catalog() -> list[dict[str, Any]]:
    with CATALOG_PATH.open(newline="", encoding="utf-8") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            rows.append(
                {
                    "id": raw["id"],
                    "name": raw["name"],
                    "category": raw["category"],
                    "description": raw["description"],
                    "seller": raw["seller"],
                    "price": int(raw["price"]),
                    "rating": float(raw["rating"]),
                    "delivery_days": int(raw["delivery_days"]),
                    "stock": int(raw["stock"]),
                    "features": _split(raw["features"]),
                    "match_reasons": _split(raw["match_reasons"]),
                    "crop_index": int(raw["crop_index"]),
                    "url": raw["url"],
                    "image": IMAGE_PATH,
                    "source_kind": "local_catalog",
                    "source_label": "Local development catalog",
                    "evidence": ["Local development catalog", "Delivery is estimated"],
                }
            )
    return rows


CATALOG = load_catalog()
