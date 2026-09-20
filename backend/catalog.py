"""Small deterministic catalog used only for local end-to-end development.

The live path remains the default when Anakin is configured. Setting
``SHOPPINGHELP_SEARCH_MODE=fixture`` makes local tests repeatable and keeps
test prompts, locations, and product data on the developer machine.
"""

from __future__ import annotations

import re
from typing import Any


FIXTURE_PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "fixture-chair-01",
        "name": "PosturePro Mesh Office Chair",
        "category": "Office chair",
        "description": "Breathable mesh back, adjustable lumbar support, and a height-adjustable seat for long work sessions.",
        "price": 10490,
        "shipping_cost": 0,
        "delivery_days": 3,
        "delivery_label": "Arrives in 3 days",
        "stock": 18,
        "rating": 4.5,
        "features": ["adjustable lumbar support", "breathable mesh", "height adjustable", "ergonomic"],
        "seller": "WorkNest",
        "url": "https://example.com/worknest/posturepro-chair",
        "image": "",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Strong support feedback with occasional complaints about armrest width.",
        "review_reliability": 0.86,
    },
    {
        "id": "fixture-chair-02",
        "name": "ErgoForm High-Back Chair",
        "category": "Office chair",
        "description": "High-back office chair with headrest, recline tension, and a shaped lumbar cushion.",
        "price": 11890,
        "shipping_cost": 299,
        "delivery_days": 4,
        "delivery_label": "Arrives in 4 days",
        "stock": 7,
        "rating": 4.3,
        "features": ["lumbar support", "reclining back", "headrest", "height adjustable"],
        "seller": "DeskTheory",
        "url": "https://example.com/desktheory/ergoform-chair",
        "image": "",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Comfortable for focused work; reviewers are split on assembly time.",
        "review_reliability": 0.81,
    },
    {
        "id": "fixture-chair-03",
        "name": "DailySeat Classic Task Chair",
        "category": "Office chair",
        "description": "Compact fabric task chair with fixed lumbar contour and a lightweight frame.",
        "price": 6990,
        "shipping_cost": 0,
        "delivery_days": 8,
        "delivery_label": "Arrives in 8 days",
        "stock": 32,
        "rating": 4.1,
        "features": ["compact", "fabric seat", "fixed lumbar contour"],
        "seller": "DailySeat",
        "url": "https://example.com/dailyseat/classic-task-chair",
        "image": "",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Good value, but delivery misses a five-day requirement.",
        "review_reliability": 0.9,
    },
    {
        "id": "fixture-chair-04",
        "name": "Luma Executive Chair",
        "category": "Office chair",
        "description": "Padded executive chair with recline, adjustable arms, and stitched faux-leather upholstery.",
        "price": 15490,
        "shipping_cost": 0,
        "delivery_days": 4,
        "delivery_label": "Arrives in 4 days",
        "stock": 3,
        "rating": 4.6,
        "features": ["adjustable arms", "recline", "padded back", "executive"],
        "seller": "Luma Office",
        "url": "https://example.com/luma/executive-chair",
        "image": "",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Premium comfort, but exceeds the stated budget.",
        "review_reliability": 0.84,
    },
    {
        "id": "fixture-shirt-01",
        "name": "Linen Everyday Overshirt",
        "category": "Clothing",
        "description": "Lightweight linen-cotton overshirt in a soft neutral palette for easy layering.",
        "price": 3290,
        "shipping_cost": 0,
        "delivery_days": 3,
        "delivery_label": "Arrives in 3 days",
        "stock": 22,
        "rating": 4.4,
        "features": ["breathable linen", "neutral palette", "easy to layer"],
        "seller": "Linen Trail",
        "url": "https://example.com/linentrail/everyday-overshirt",
        "image": "/assets/editorial-outfit-triptych.png",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Consistent fabric quality across verified buyer reviews.",
        "review_reliability": 0.89,
    },
]


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


class FixtureCatalogClient:
    """A local catalog adapter with real constraint filtering semantics."""

    configured = True

    def search(self, brief: dict[str, Any], num_results: int = 10) -> dict[str, Any]:
        query_tokens = _tokens(" ".join([
            str(brief.get("category") or ""),
            str(brief.get("description") or ""),
            " ".join(str(value) for value in brief.get("must_have") or []),
        ]))
        category = str(brief.get("category") or "").lower()
        candidates = FIXTURE_PRODUCTS
        if any(token in category for token in ("chair", "ergonomic", "furniture")) or "chair" in query_tokens:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] == "Office chair"]
        elif any(token in category for token in ("shirt", "fashion", "clothing", "outfit")) or "shirt" in query_tokens:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] == "Clothing"]
        return {"results": [dict(item) for item in candidates[: max(1, min(num_results, 10))]]}
