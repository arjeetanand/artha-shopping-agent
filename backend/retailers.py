"""Provider-neutral contracts for retailer and delivery integrations.

Sources include Tavily or Anakin web search/extraction and the local
fixture catalog. This module keeps the rest of the workflow independent from
those providers so dedicated marketplace adapters can be added without
changing ranking, clarification, or checkout code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DeliveryQuote:
    """A delivery result with an explicit unknown/unverified state."""

    pincode: str | None
    days: int | None
    label: str
    serviceable: bool | None
    shipping_cost: int | None = None
    status: str = "unverified"
    provider: str = "unknown"
    checked_at: str = field(default_factory=_now_iso)


@dataclass(frozen=True)
class ProductVariant:
    color: str | None = None
    size: str | None = None
    available: bool | None = None
    price: int | None = None
    stock: int | None = None
    sku: str | None = None


@dataclass
class RetailerProduct:
    id: str
    name: str
    url: str
    price: int | None
    seller: str
    provider: str
    source_status: str = "unverified"
    delivery: DeliveryQuote | None = None
    variants: list[ProductVariant] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "price": self.price,
            "seller": self.seller,
            "source_provider": self.provider,
            "source_status": self.source_status,
            "delivery": {
                "pincode": self.delivery.pincode,
                "days": self.delivery.days,
                "label": self.delivery.label,
                "serviceable": self.delivery.serviceable,
                "shipping_cost": self.delivery.shipping_cost,
                "status": self.delivery.status,
                "provider": self.delivery.provider,
                "checked_at": self.delivery.checked_at,
            } if self.delivery else None,
            "variants": [
                {
                    "color": variant.color,
                    "size": variant.size,
                    "available": variant.available,
                    "price": variant.price,
                    "stock": variant.stock,
                    "sku": variant.sku,
                }
                for variant in self.variants
            ],
            "evidence": list(self.evidence),
            "fetched_at": self.fetched_at,
        }


class RetailerAdapter(Protocol):
    name: str

    def search(self, brief: dict[str, Any]) -> list[RetailerProduct]:
        """Search the provider and return source-linked normalized products."""

    def check_delivery(self, product: RetailerProduct, pincode: str) -> DeliveryQuote:
        """Check serviceability for a concrete product and pincode."""


class FixtureRetailerAdapter:
    """Deterministic adapter used by local tests and development."""

    name = "fixture_catalog"

    def search(self, brief: dict[str, Any]) -> list[RetailerProduct]:
        from .catalog import FixtureCatalogClient

        results = FixtureCatalogClient().search(brief, num_results=10).get("results") or []
        return [normalize_product(item, provider=self.name, pincode=brief.get("pincode")) for item in results]

    def check_delivery(self, product: RetailerProduct, pincode: str) -> DeliveryQuote:
        days = product.delivery.days if product.delivery else None
        return DeliveryQuote(
            pincode=pincode,
            days=days,
            label=product.delivery.label if product.delivery else "Confirm at retailer",
            serviceable=True if days is not None else None,
            shipping_cost=product.delivery.shipping_cost if product.delivery else None,
            status="catalog" if days is not None else "unverified",
            provider=self.name,
        )


class RetailerRegistry:
    """Small registry for swappable marketplace and delivery adapters."""

    def __init__(self, adapters: list[RetailerAdapter] | None = None) -> None:
        self.adapters = list(adapters or [])

    def names(self) -> list[str]:
        return [str(adapter.name) for adapter in self.adapters]

    def search(self, brief: dict[str, Any]) -> list[RetailerProduct]:
        products: list[RetailerProduct] = []
        for adapter in self.adapters:
            try:
                products.extend(adapter.search(brief))
            except Exception:
                # One unavailable marketplace should not hide results from the
                # other providers; its absence remains visible in status data.
                continue
        return products


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_product(raw: dict[str, Any], *, provider: str, pincode: str | None = None) -> RetailerProduct:
    """Normalize a raw catalog/provider item without inventing unknown fields."""
    price = _int_or_none(raw.get("price"))
    days = _int_or_none(raw.get("delivery_days"))
    shipping = _int_or_none(raw.get("shipping_cost"))
    delivery = DeliveryQuote(
        pincode=pincode,
        days=days,
        label=str(raw.get("delivery_label") or "Confirm at retailer"),
        serviceable=days is not None,
        shipping_cost=shipping,
        status="catalog" if days is not None else "unverified",
        provider=provider,
    )
    variants = []
    raw_variants = raw.get("variants") if isinstance(raw.get("variants"), list) else []
    for item in raw_variants:
        if not isinstance(item, dict):
            continue
        variants.append(
            ProductVariant(
                color=str(item.get("color") or "") or None,
                size=str(item.get("size") or "") or None,
                available=item.get("available") if isinstance(item.get("available"), bool) else None,
                price=_int_or_none(item.get("price")),
                stock=_int_or_none(item.get("stock")),
                sku=str(item.get("sku") or "") or None,
            )
        )
    return RetailerProduct(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or raw.get("title") or "Retailer product"),
        url=str(raw.get("url") or raw.get("link") or ""),
        price=price,
        seller=str(raw.get("seller") or raw.get("brand") or provider),
        provider=provider,
        source_status="verified" if price is not None or days is not None else "unverified",
        delivery=delivery,
        variants=variants,
        evidence=[str(value) for value in (raw.get("evidence") or []) if str(value).strip()],
    )


def provider_status(*, live_configured: bool = False, fixture_enabled: bool = False, provider: str = "anakin") -> dict[str, Any]:
    return {
        "configured": bool(live_configured or fixture_enabled),
        "providers": ([provider] if live_configured else []) + (["fixture_catalog"] if fixture_enabled else []),
        "dedicated_marketplace_adapters": [],
        "delivery_verification": "source_reported_only" if live_configured else "fixture_only" if fixture_enabled else "unavailable",
    }
