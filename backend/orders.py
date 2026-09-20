"""Purchase and tracking service.

The sandbox gateway is intentionally explicit: it creates a local order record
for repeatable development and never represents it as a merchant charge. A
production payment/merchant adapter can implement the same gateway contract
without changing the UI or order-tracking model.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from .db import db, now_iso
from .settings import is_production, setting


class OrderError(ValueError):
    pass


def _money(value: Any) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _safe_item(item: dict[str, Any]) -> dict[str, Any]:
    product_price = _money(item.get("price"))
    shipping = _money(item.get("shipping_cost"))
    total = _money(item.get("total_price")) or product_price + shipping
    return {
        "id": str(item.get("id") or uuid.uuid4().hex)[:120],
        "name": str(item.get("name") or "Retailer product")[:180],
        "seller": str(item.get("seller") or "Retailer")[:100],
        "price": product_price,
        "shipping_cost": shipping,
        "total_price": total,
        "delivery_days": _money(item.get("delivery_days")) or None,
        "delivery_label": str(item.get("delivery_label") or "Confirm at retailer")[:120],
        "url": str(item.get("url") or "")[:1000],
        "source_kind": str(item.get("source_kind") or "source")[:60],
    }


def _timeline(status: str, created_at: str, delivery_days: int) -> list[dict[str, Any]]:
    expected = date.today() + timedelta(days=max(delivery_days, 1))
    return [
        {"key": "confirmed", "label": "Order confirmed", "detail": "Your selected items were recorded and the seller handoff is ready.", "complete": status not in {"cancelled"}, "at": created_at},
        {"key": "preparing", "label": "Preparing", "detail": "The seller is preparing the order.", "complete": status in {"preparing", "shipped", "out_for_delivery", "delivered"}, "at": None},
        {"key": "shipped", "label": "Shipped", "detail": "Tracking will appear when the seller confirms dispatch.", "complete": status in {"shipped", "out_for_delivery", "delivered"}, "at": None},
        {"key": "out_for_delivery", "label": "Out for delivery", "detail": "Expected by the seller's delivery estimate.", "complete": status in {"out_for_delivery", "delivered"}, "at": None},
        {"key": "delivered", "label": "Delivered", "detail": f"Expected by {expected.strftime('%a, %d %b')}.", "complete": status == "delivered", "at": None},
    ]


def create_order(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    if not payload.get("confirmed"):
        raise OrderError("Order confirmation is required before checkout.")
    provider = setting("PAYMENT_PROVIDER", "sandbox").lower()
    if is_production() and provider == "sandbox":
        raise OrderError("A production payment provider is not configured. No order was created.")
    if provider != "sandbox":
        raise OrderError(f"Payment provider '{provider}' has no enabled merchant adapter. No order was created.")

    plan_id = str(payload.get("plan_id") or "").strip() or None
    plan = db.get_purchase_plan(plan_id, user_id) if plan_id else None
    raw_items = payload.get("products") or (plan or {}).get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise OrderError("Select at least one product before checkout.")
    items = [_safe_item(item) for item in raw_items if isinstance(item, dict)]
    items = [item for item in items if item["name"] and item["total_price"] > 0]
    if not items:
        raise OrderError("The selected products do not contain a verified payable total.")

    total = sum(item["total_price"] for item in items)
    created_at = now_iso()
    delivery_days = max((item.get("delivery_days") or 5 for item in items), default=5)
    order = {
        "id": f"ORD-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
        "user_id": user_id,
        "plan_id": plan_id,
        "status": "confirmed",
        "payment_status": "sandbox_authorized",
        "payment_provider": provider,
        "currency": "INR",
        "total": total,
        "items": items,
        "location": str(payload.get("location") or (payload.get("intent") or {}).get("location") or "your delivery location")[:160],
        "delivery_days": delivery_days,
        "created_at": created_at,
        "updated_at": created_at,
        "timeline": _timeline("confirmed", created_at, delivery_days),
        "notice": "Sandbox order recorded locally. No card was charged and no merchant checkout was submitted." if provider == "sandbox" else "Payment authorization confirmed by the configured provider.",
    }
    return db.save_order(order)


def list_orders(user_id: str) -> list[dict[str, Any]]:
    return db.list_orders(user_id)


def get_order(order_id: str, user_id: str) -> dict[str, Any]:
    order = db.get_order(order_id, user_id)
    if not order:
        raise OrderError("Order not found.")
    return order


def cancel_order(order_id: str, user_id: str) -> dict[str, Any]:
    order = get_order(order_id, user_id)
    if order.get("status") in {"delivered", "cancelled"}:
        raise OrderError("This order can no longer be cancelled.")
    order["status"] = "cancelled"
    order["payment_status"] = "voided"
    order["updated_at"] = now_iso()
    order["timeline"] = [{**step, "complete": False} for step in order.get("timeline") or []]
    order["notice"] = "Order cancelled in the local purchase tracker. Confirm cancellation with the retailer when using a live merchant adapter."
    return db.update_order(order)
