"""Offline contracts for provider-neutral retailer integration objects."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.retailers import FixtureRetailerAdapter, RetailerRegistry, normalize_product  # noqa: E402


def main() -> None:
    product = normalize_product(
        {
            "id": "dress-1",
            "name": "Red dress",
            "url": "https://retailer.example/dress-1",
            "price": 999,
            "delivery_days": 3,
            "delivery_label": "Arrives in 3 days",
            "variants": [{"color": "red", "size": "M", "available": True, "stock": 2}],
            "evidence": ["Retailer price"],
        },
        provider="fixture_catalog",
        pincode="560001",
    )
    assert product.price == 999
    assert product.delivery and product.delivery.pincode == "560001"
    assert product.delivery.status == "catalog"
    assert product.variants[0].color == "red"
    assert product.as_dict()["source_status"] == "verified"

    registry = RetailerRegistry([FixtureRetailerAdapter()])
    results = registry.search({"category": "Clothing", "pincode": "560001"})
    assert results and registry.names() == ["fixture_catalog"]
    print("retailer_contracts_ok", len(results))


if __name__ == "__main__":
    main()
