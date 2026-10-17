"""Small deterministic catalog used only for local end-to-end development.

The live path remains the default when live retailer scraping is active. Setting
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
        "brand": "WorkNest",
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
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 132, "rating": 4.5, "signal": "Low duplication signal"},
            {"name": "Independent discussion", "count": 24, "rating": 4.2, "signal": "Small but consistent sample"},
        ],
        "review_analysis": {"label": "Mostly consistent", "detail": "Ratings and written feedback point to the same lumbar-support trade-off."},
        "price_history": {"low_90d": 9990, "median_90d": 10990, "high_90d": 12490, "trend_label": "Near its 90-day low"},
    },
    {
        "id": "fixture-chair-02",
        "name": "ErgoForm High-Back Chair",
        "category": "Office chair",
        "brand": "DeskTheory",
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
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 87, "rating": 4.3, "signal": "Some repeated phrasing"},
            {"name": "Independent discussion", "count": 13, "rating": 4.0, "signal": "Limited sample"},
        ],
        "review_analysis": {"label": "Mixed signals", "detail": "Comfort feedback is positive; assembly complaints are more variable."},
        "price_history": {"low_90d": 11490, "median_90d": 12290, "high_90d": 13990, "trend_label": "Typical 90-day price"},
    },
    {
        "id": "fixture-chair-03",
        "name": "DailySeat Classic Task Chair",
        "category": "Office chair",
        "brand": "DailySeat",
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
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 204, "rating": 4.1, "signal": "Stable rating distribution"},
            {"name": "Independent discussion", "count": 31, "rating": 4.0, "signal": "No obvious anomaly"},
        ],
        "review_analysis": {"label": "Strong signal", "detail": "Large, stable review sample supports the value claim."},
        "price_history": {"low_90d": 6790, "median_90d": 7490, "high_90d": 8290, "trend_label": "At a 90-day low"},
    },
    {
        "id": "fixture-chair-04",
        "name": "Luma Executive Chair",
        "category": "Office chair",
        "brand": "Luma Office",
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
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 63, "rating": 4.6, "signal": "Low duplication signal"},
            {"name": "Independent discussion", "count": 8, "rating": 4.4, "signal": "Limited sample"},
        ],
        "review_analysis": {"label": "Mostly consistent", "detail": "Comfort claims are consistent, but the premium is not justified by the current budget."},
        "price_history": {"low_90d": 14490, "median_90d": 15990, "high_90d": 17990, "trend_label": "Below its 90-day median"},
    },
    {
        "id": "fixture-shirt-01",
        "name": "Linen Everyday Overshirt",
        "category": "Clothing",
        "brand": "Linen Trail",
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
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 118, "rating": 4.4, "signal": "Low duplication signal"},
            {"name": "Independent discussion", "count": 19, "rating": 4.3, "signal": "Consistent sentiment"},
        ],
        "review_analysis": {"label": "Strong signal", "detail": "Fabric quality and fit feedback remain consistent across sources."},
        "price_history": {"low_90d": 2990, "median_90d": 3490, "high_90d": 3990, "trend_label": "Below its 90-day median"},
    },
    {
        "id": "fixture-tshirt-01",
        "name": "Uniqlo AIRism Cotton Relaxed Crew Neck T-Shirt",
        "category": "T-shirt",
        "brand": "Uniqlo",
        "description": "Relaxed-fit breathable cotton-blend T-shirt in olive and beige monochrome palette, ideal for coastal and Goa travel.",
        "price": 1290,
        "shipping_cost": 0,
        "delivery_days": 3,
        "delivery_label": "Arrives in 3 days",
        "stock": 14,
        "rating": 4.6,
        "color": "olive",
        "colors": ["olive", "beige", "off-white", "charcoal"],
        "size": "M",
        "sizes": ["S", "M", "L", "XL"],
        "variants": [
            {"color": "olive", "size": "S", "available": True, "price": 1290, "stock": 6},
            {"color": "olive", "size": "M", "available": True, "price": 1290, "stock": 14},
            {"color": "beige", "size": "M", "available": True, "price": 1290, "stock": 9},
            {"color": "off-white", "size": "M", "available": True, "price": 1290, "stock": 11},
            {"color": "charcoal", "size": "M", "available": True, "price": 1290, "stock": 8},
        ],
        "features": ["breathable", "relaxed fit", "neutral palette", "cotton"],
        "seller": "Amazon India",
        "url": "https://www.amazon.in/dp/B0UNIQLOTEE01",
        "image": "/assets/editorial-outfit-triptych.png",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Praised for breathable weight and clean drape in humid weather.",
        "review_reliability": 0.91,
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 210, "rating": 4.6, "signal": "Low duplication signal"},
        ],
        "review_analysis": {"label": "Strong signal", "detail": "Consistent fit and fabric reviews for travel wear."},
        "price_history": {"low_90d": 1190, "median_90d": 1490, "high_90d": 1690, "trend_label": "Below its 90-day median"},
    },
    {
        "id": "fixture-tshirt-02",
        "name": "Jack & Jones Coastal Textured Relaxed Fit T-Shirt",
        "category": "T-shirt",
        "brand": "Jack & Jones",
        "description": "Textured knit crew-neck T-shirt with relaxed drop-shoulder cut in earthy olive/beige tones.",
        "price": 1449,
        "shipping_cost": 0,
        "delivery_days": 4,
        "delivery_label": "Arrives in 4 days",
        "stock": 9,
        "rating": 4.4,
        "color": "beige",
        "colors": ["beige", "olive", "white", "black"],
        "size": "M",
        "sizes": ["S", "M", "L"],
        "variants": [
            {"color": "beige", "size": "M", "available": True, "price": 1449, "stock": 9},
            {"color": "olive", "size": "M", "available": True, "price": 1449, "stock": 5},
            {"color": "white", "size": "M", "available": True, "price": 1449, "stock": 7},
        ],
        "features": ["breathable", "textured knit", "neutral palette", "cotton"],
        "seller": "Flipkart",
        "url": "https://www.flipkart.com/jack-jones-coastal-tee/p/itm700502570",
        "image": "/assets/editorial-outfit-triptych.png",
        "source_kind": "sandbox_catalog",
        "source_label": "Local catalog fixture",
        "evidence": ["Catalog price", "Seller stock feed", "Delivery estimate"],
        "review_summary": "Soft textured weave that holds shape well after washing.",
        "review_reliability": 0.87,
        "review_sources": [
            {"name": "Verified buyer reviews", "count": 94, "rating": 4.4, "signal": "Consistent sizing feedback"},
        ],
        "review_analysis": {"label": "Mostly consistent", "detail": "Reviewers confirm true-to-size M fit."},
        "price_history": {"low_90d": 1299, "median_90d": 1499, "high_90d": 1799, "trend_label": "Typical 90-day price"},
    },
]


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


class FixtureCatalogClient:
    """A local catalog adapter with real constraint filtering semantics."""

    configured = True

    def search(self, brief: dict[str, Any], num_results: int = 10) -> dict[str, Any]:
        raw_desc = " ".join([
            str(brief.get("category") or ""),
            str(brief.get("description") or ""),
            str(brief.get("raw_text") or ""),
            " ".join(str(value) for value in brief.get("must_have") or []),
        ]).lower()
        query_tokens = _tokens(raw_desc)
        category = str(brief.get("category") or "").lower()
        is_tshirt = bool(re.search(r"\b(?:t[\s-]*shirts?|tees?)\b", f"{category} {raw_desc}"))
        if any(token in category for token in ("chair", "ergonomic", "furniture")) or "chair" in query_tokens:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] == "Office chair"]
        elif is_tshirt:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] in {"T-shirt", "Clothing"}]
        elif any(token in category for token in ("shirt", "fashion", "clothing", "outfit")) or "shirt" in query_tokens:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] == "Clothing"]
        else:
            candidates = [item for item in FIXTURE_PRODUCTS if item["category"] != "T-shirt"]
        brand = str(brief.get("brand") or "").lower().strip()
        if brand:
            candidates = sorted(
                candidates,
                key=lambda item: 0 if brand in " ".join(str(item.get(field) or "") for field in ("brand", "seller", "name")).lower() else 1,
            )
        return {"results": [dict(item) for item in candidates[: max(1, min(num_results, 10))]]}
