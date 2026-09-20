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


ORDER_STATUSES = ("confirmed", "preparing", "shipped", "out_for_delivery", "delivered")


def _money(value: Any) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _safe_item(item: dict[str, Any]) -> dict[str, Any]:
    product_price = _money(item.get("price"))
    shipping = _money(item.get("shipping_cost"))
    unit_total = _money(item.get("unit_total")) or _money(item.get("total_price")) or product_price + shipping
    quantity = max(1, min(_money(item.get("quantity")) or 1, 99))
    total = unit_total * quantity
    return {
        "id": str(item.get("id") or uuid.uuid4().hex)[:120],
        "name": str(item.get("name") or "Retailer product")[:180],
        "seller": str(item.get("seller") or "Retailer")[:100],
        "brand": str(item.get("brand") or "")[:100],
        "quantity": quantity,
        "price": product_price,
        "shipping_cost": shipping,
        "total_price": unit_total,
        "unit_total": unit_total,
        "line_total": total,
        "delivery_days": _money(item.get("delivery_days")) or None,
        "delivery_label": str(item.get("delivery_label") or "Confirm at retailer")[:120],
        "url": str(item.get("url") or "")[:1000],
        "source_kind": str(item.get("source_kind") or "source")[:60],
    }


def _timeline(status: str, created_at: str, delivery_days: int) -> list[dict[str, Any]]:
    expected = date.today() + timedelta(days=max(delivery_days, 1))
    progress_status = "delivered" if status in {"return_requested", "refunded"} else status
    return_step = {"key": "return", "label": "Return / refund", "detail": "Return eligibility and refund status are handled by the retailer adapter.", "complete": status in {"return_requested", "refunded"}, "at": None}
    return [
        {"key": "confirmed", "label": "Order confirmed", "detail": "Your selected items were recorded and the seller handoff is ready.", "complete": progress_status != "cancelled", "at": created_at},
        {"key": "preparing", "label": "Preparing", "detail": "The seller is preparing the order.", "complete": progress_status in {"preparing", "shipped", "out_for_delivery", "delivered"}, "at": None},
        {"key": "shipped", "label": "Shipped", "detail": "Tracking will appear when the seller confirms dispatch.", "complete": progress_status in {"shipped", "out_for_delivery", "delivered"}, "at": None},
        {"key": "out_for_delivery", "label": "Out for delivery", "detail": "Expected by the seller's delivery estimate.", "complete": progress_status in {"out_for_delivery", "delivered"}, "at": None},
        {"key": "delivered", "label": "Delivered", "detail": f"Expected by {expected.strftime('%a, %d %b')}.", "complete": progress_status == "delivered", "at": None},
        return_step,
    ]


def canonical_order_preview(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    if not payload.get("confirmed"):
        raise OrderError("Order confirmation is required before checkout.")
    plan_id = str(payload.get("plan_id") or "").strip() or None
    plan = db.get_purchase_plan(plan_id, user_id) if plan_id else None
    if plan_id and not plan:
        raise OrderError("Purchase plan not found.")
    search_id = str(payload.get("search_id") or "").strip() or None
    submitted_items = payload.get("products") or []
    if plan:
        raw_items = (plan or {}).get("items") or []
    elif search_id:
        canonical_products = {str(item.get("id")): item for item in db.get_search_products(search_id) if isinstance(item, dict)}
        if not isinstance(submitted_items, list) or not submitted_items:
            raise OrderError("Select at least one product before checkout.")
        requested_ids = [str(item.get("id")) for item in submitted_items if isinstance(item, dict) and item.get("id")]
        if not requested_ids or any(product_id not in canonical_products for product_id in requested_ids):
            raise OrderError("The selected product is no longer present in the verified search result.")
        raw_items = [canonical_products[product_id] for product_id in requested_ids]
    else:
        raw_items = submitted_items
    if not isinstance(raw_items, list) or not raw_items:
        raise OrderError("Select at least one product before checkout.")
    items = [_safe_item(item) for item in raw_items if isinstance(item, dict)]
    items = [item for item in items if item["name"] and item["total_price"] > 0]
    if not items:
        raise OrderError("The selected products do not contain a verified payable total.")

    total = sum(item["line_total"] for item in items)
    delivery_days = max((item.get("delivery_days") or 5 for item in items), default=5)
    return {
        "plan_id": plan_id,
        "search_id": search_id,
        "items": items,
        "total": total,
        "delivery_days": delivery_days,
        "location": str(payload.get("location") or (payload.get("intent") or {}).get("location") or "your delivery location")[:160],
    }


def create_order(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    provider = setting("PAYMENT_PROVIDER", "sandbox").lower()
    if is_production() and provider == "sandbox":
        raise OrderError("A production payment provider is not configured. No order was created.")
    if provider not in {"sandbox", "razorpay"}:
        raise OrderError(f"Payment provider '{provider}' has no enabled merchant adapter. No order was created.")
    if provider == "razorpay" and not payload.get("payment_verified"):
        raise OrderError("Complete the secure payment step before recording this order.")

    preview = canonical_order_preview(payload, user_id)
    created_at = now_iso()
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    order = {
        "id": f"ORD-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
        "user_id": user_id,
        "plan_id": preview["plan_id"],
        "search_id": preview["search_id"],
        "status": "confirmed",
        "payment_status": "sandbox_authorized" if provider == "sandbox" else "paid",
        "payment_provider": provider,
        "payment_reference": str(payment.get("payment_id") or "")[:120] or None,
        "payment_order_id": str(payment.get("order_id") or "")[:120] or None,
        "currency": "INR",
        "total": preview["total"],
        "items": preview["items"],
        "location": preview["location"],
        "delivery_days": preview["delivery_days"],
        "created_at": created_at,
        "updated_at": created_at,
        "timeline": _timeline("confirmed", created_at, preview["delivery_days"]),
        "notice": "Sandbox order recorded locally. No card was charged and no merchant checkout was submitted." if provider == "sandbox" else "Razorpay payment signature verified. Retailer fulfillment still requires a configured merchant adapter.",
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


def advance_order(order_id: str, user_id: str) -> dict[str, Any]:
    order = get_order(order_id, user_id)
    status = order.get("status")
    if status not in ORDER_STATUSES[:-1]:
        raise OrderError("This order has no further sandbox delivery step.")
    next_status = ORDER_STATUSES[ORDER_STATUSES.index(status) + 1]
    order["status"] = next_status
    order["updated_at"] = now_iso()
    order["timeline"] = _timeline(next_status, order["created_at"], order.get("delivery_days") or 5)
    order["notice"] = f"Sandbox tracker advanced to {next_status.replace('_', ' ')}. Live status requires a retailer webhook."
    return db.update_order(order)


def request_return(order_id: str, user_id: str) -> dict[str, Any]:
    order = get_order(order_id, user_id)
    if order.get("status") != "delivered":
        raise OrderError("A return can be requested after the order is delivered.")
    order["status"] = "return_requested"
    order["refund_status"] = "pending"
    order["updated_at"] = now_iso()
    order["timeline"] = _timeline("return_requested", order["created_at"], order.get("delivery_days") or 5)
    order["notice"] = "Sandbox return request recorded. No retailer return or refund has been submitted."
    return db.update_order(order)


def complete_refund(order_id: str, user_id: str) -> dict[str, Any]:
    order = get_order(order_id, user_id)
    if order.get("status") != "return_requested":
        raise OrderError("Request a return before recording a sandbox refund.")
    order["status"] = "refunded"
    order["refund_status"] = "sandbox_refunded"
    order["updated_at"] = now_iso()
    order["timeline"] = _timeline("refunded", order["created_at"], order.get("delivery_days") or 5)
    order["notice"] = "Sandbox refund recorded locally. No payment provider or retailer was contacted."
    return db.update_order(order)
