"""Price comparisons backed by direct page checks and recorded observations."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote_plus, urlparse, urlsplit, urlunsplit

from .db import Database, now_iso


def _normalized(value: Any) -> str:
    return re.sub(r"[^\w]+", " ", str(value or "").casefold()).strip()


def _http_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return parsed.hostname
    except ValueError:
        pass
    return ""


def _identity_url(url: str) -> str:
    """Ignore tracking decorations while preserving product and variant parameters."""
    parsed = urlsplit(url)
    tracking = {"gclid", "fbclid", "msclkid", "igshid", "mc_cid", "mc_eid"}
    query = "&".join(
        part for part in parsed.query.split("&") if part and not (
            (key := unquote_plus(part.split("=", 1)[0]).casefold()).startswith("utm_") or key in tracking
        )
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def valid_gtin(value: Any) -> str | None:
    """Return a GTIN only when its length and GS1 check digit are valid."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) not in {8, 12, 13, 14}:
        return None
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(value[:-1])))
    return value if (10 - total % 10) % 10 == int(value[-1]) else None


def product_identity(product: dict[str, Any]) -> tuple[str, str]:
    brand = _normalized(product.get("brand"))
    name = _normalized(product.get("name"))
    def variant_value(field: str, plural: str) -> tuple[str, bool]:
        selected = _normalized(product.get(field))
        if selected:
            return selected, False
        options = product.get(plural) or []
        if not options:
            options = [variant.get(field) for variant in (product.get("variants") or []) if isinstance(variant, dict)]
        values = {_normalized(value) for value in options if _normalized(value)}
        return (next(iter(values)), False) if len(values) == 1 else ("", len(values) > 1)

    color, ambiguous_color = variant_value("color", "colors")
    size, ambiguous_size = variant_value("size", "sizes")
    gtin = valid_gtin(product.get("gtin")) if product.get("gtin_source") == "direct_product_jsonld" else None
    if gtin and not (ambiguous_color or ambiguous_size):
        return f"gtin:{gtin}|variant:{color}|{size}", "gtin"
    # A shared title alone can hide different size/colour variants. Only a
    # fully identified variant may share prices across retailer URLs.
    if brand and brand not in {"unknown", "generic", "n a"} and name and color and size and not (ambiguous_color or ambiguous_size):
        variant = f"{color}|{size}"
        return f"brand:{brand}|name:{name}|variant:{variant}", "brand_and_exact_title"
    url = str(product.get("url") or "")
    return (f"url:{_identity_url(url)}|variant:{color}|{size}", "source_url_only") if _http_host(url) else ("", "unmatched")


def verified_price_offer(product: dict[str, Any], product_key: str, observed_at: str) -> dict[str, Any] | None:
    if product.get("source_kind") not in (None, "", "live_web"):
        return None
    verification = product.get("price_verification")
    if product.get("research_status") != "complete" or verification not in {"matched", "direct", "mismatch"}:
        return None
    price = product.get("price")
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        return None
    if verification == "mismatch" and product.get("direct_page_price") != price:
        return None
    currency = str(product.get("currency") or "").upper()
    if currency not in {"INR", "₹"}:
        return None
    url = str(product.get("url") or "")
    host = _http_host(url)
    if not product_key or not host:
        return None
    return {
        "product_key": product_key,
        "product_id": str(product.get("id") or ""),
        "source_url": url,
        "seller": str(product.get("seller") or host),
        "price": price,
        "currency": "INR",
        "source_status": "direct_page_price_changed" if verification == "mismatch" else "direct_page",
        "observed_at": observed_at,
    }


def _history(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "unknown", "observations": [], "observation_count": 0, "observed_low": None,
                "observed_high": None, "first_observed_at": None, "last_observed_at": None,
                "trend_label": "No recorded price history yet"}
    first, last = rows[0]["observed_at"], rows[-1]["observed_at"]
    return {
        "status": "observed" if first != last else "first_observation",
        "observations": rows,
        "observation_count": len(rows),
        "observed_low": min(row["price"] for row in rows),
        "observed_high": max(row["price"] for row in rows),
        "first_observed_at": first,
        "last_observed_at": last,
        "trend_label": f"Recorded from {first[:10]} to {last[:10]}" if first != last else f"First recorded check on {first[:10]}",
    }


def enrich_price_evidence(
    database: Database,
    products: list[dict[str, Any]],
    *,
    source_mode: str | None,
    observed_at: str | None = None,
) -> list[dict[str, Any]]:
    """Attach current exact-match offers and durable history from direct page checks."""
    if source_mode != "live":
        for product in products:
            existing = product.get("price_history") if isinstance(product.get("price_history"), dict) else {}
            demo = source_mode == "sandbox" and bool(existing)
            product["price_history"] = {
                **(existing if demo else {}), "status": "fixture" if demo else "unknown",
                "trend_label": f"Demo data: {existing.get('trend_label') or 'price history'}" if demo else "No recorded price history yet",
                "observations": [],
            }
            product["current_offers"] = []
            product["lowest_current_offer"] = None
            product["same_product_match"] = "unmatched"
        return products

    checked_at = observed_at or now_iso()
    keys: list[str] = []
    current: dict[tuple[str, str], dict[str, Any]] = {}
    conflicting: set[tuple[str, str]] = set()
    for product in products:
        key, basis = product_identity(product)
        product["product_key"] = key
        product["same_product_match"] = basis
        keys.append(key)
        offer = verified_price_offer(product, key, checked_at)
        if offer:
            identity = (key, offer["source_url"])
            if identity in current and current[identity]["price"] != offer["price"]:
                conflicting.add(identity)
            else:
                current.setdefault(identity, offer)
    for identity in conflicting:
        current.pop(identity, None)
    offers = list(current.values())
    database.record_price_observations(offers)
    current_by_key: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        current_by_key.setdefault(offer["product_key"], []).append({field: value for field, value in offer.items() if field != "product_key"})
    for offer_list in current_by_key.values():
        offer_list.sort(key=lambda item: (item["price"], item["seller"]))
    histories = {key: _history(database.price_observations(key)) for key in set(keys)}
    for product, key in zip(products, keys):
        product["current_offers"] = current_by_key.get(key, [])
        product["lowest_current_offer"] = product["current_offers"][0] if product["current_offers"] else None
        product["price_history"] = histories[key]
    return products
