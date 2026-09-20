"""Optional Razorpay Standard Checkout adapter.

The adapter is deliberately opt-in. Local development keeps using the
explicit sandbox tracker; production must provide both Razorpay credentials
and a verified checkout callback before an order is recorded.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from datetime import date
from typing import Any

from .db import db, now_iso
from .orders import OrderError, canonical_order_preview, create_order
from .settings import is_production, setting


RAZORPAY_API_BASE = setting("RAZORPAY_API_BASE_URL", "https://api.razorpay.com/v1").rstrip("/")


class PaymentError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def payment_status() -> dict[str, Any]:
    provider = setting("PAYMENT_PROVIDER", "sandbox").lower()
    configured = (provider == "sandbox" and not is_production()) or (provider == "razorpay" and bool(setting("RAZORPAY_KEY_ID") and setting("RAZORPAY_KEY_SECRET")))
    return {
        "provider": provider,
        "configured": configured,
        "mode": "local sandbox" if provider == "sandbox" and configured else "disabled in production" if provider == "sandbox" else "server-side checkout" if configured else "missing credentials",
    }


def _require_razorpay() -> tuple[str, str]:
    if setting("PAYMENT_PROVIDER", "sandbox").lower() != "razorpay":
        raise PaymentError("Razorpay checkout is not enabled for this environment.")
    key_id = setting("RAZORPAY_KEY_ID")
    key_secret = setting("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise PaymentError("Razorpay is selected but RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are missing.", 503)
    return key_id, key_secret


def _razorpay_order(amount: int, receipt: str, notes: dict[str, str], key_id: str, key_secret: str) -> dict[str, Any]:
    payload = json.dumps(
        {"amount": amount * 100, "currency": "INR", "receipt": receipt[:40], "notes": notes},
        ensure_ascii=False,
    ).encode("utf-8")
    credentials = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        f"{RAZORPAY_API_BASE}/orders",
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Basic {credentials}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError) as error:
        raise PaymentError("Razorpay could not create a payment order. No Artha order was recorded.", 502) from error
    if not isinstance(body, dict) or not body.get("id"):
        raise PaymentError("Razorpay returned an invalid payment order. No Artha order was recorded.", 502)
    return body


def create_payment_order(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    key_id, key_secret = _require_razorpay()
    user_id = str(user.get("id") or "")
    if not user_id:
        raise PaymentError("A signed-in user is required before payment.", 401)
    if not payload.get("search_id") and not payload.get("plan_id"):
        raise PaymentError("Payment must be started from a verified search or saved purchase plan.")
    preview = canonical_order_preview(payload, user_id)
    provider_order = _razorpay_order(
        preview["total"],
        f"artha-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
        {"user_id": user_id[:40], "search_id": str(preview.get("search_id") or "")[:40]},
        key_id,
        key_secret,
    )
    attempt_payload = {
        "confirmed": True,
        "search_id": preview.get("search_id"),
        "plan_id": preview.get("plan_id"),
        "products": [{"id": item["id"], "quantity": item["quantity"]} for item in preview["items"]],
        "location": preview["location"],
    }
    timestamp = now_iso()
    attempt = {
        "id": f"pay-{uuid.uuid4().hex}",
        "user_id": user_id,
        "provider": "razorpay",
        "provider_order_id": str(provider_order["id"])[:120],
        "amount": preview["total"],
        "currency": "INR",
        "status": "created",
        "purchase_payload": attempt_payload,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    db.save_payment_attempt(attempt)
    return {
        "provider": "razorpay",
        "key_id": key_id,
        "order_id": str(provider_order["id"]),
        "amount": int(provider_order.get("amount") or preview["total"] * 100),
        "currency": str(provider_order.get("currency") or "INR"),
        "name": "Artha",
        "description": "Confirmed Artha purchase plan",
        "prefill": {"name": str(user.get("name") or "")[:120], "email": str(user.get("email") or "")[:180]},
    }


def verify_payment(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    _, key_secret = _require_razorpay()
    user_id = str(user.get("id") or "")
    order_id = str(payload.get("razorpay_order_id") or "").strip()
    payment_id = str(payload.get("razorpay_payment_id") or "").strip()
    signature = str(payload.get("razorpay_signature") or "").strip()
    if not order_id or not payment_id or not signature:
        raise PaymentError("Razorpay did not return a complete payment verification payload.")
    attempt = db.get_payment_attempt(order_id, user_id)
    if not attempt:
        raise PaymentError("Payment order not found for this signed-in user.", 404)
    if attempt.get("status") != "created":
        raise PaymentError("This payment attempt has already been completed or rejected.")
    expected = hmac.new(key_secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        attempt["status"] = "rejected"
        attempt["updated_at"] = now_iso()
        db.update_payment_attempt(attempt)
        raise PaymentError("Razorpay payment verification failed. No order was recorded.", 400)
    purchase_payload = attempt.get("purchase_payload") if isinstance(attempt.get("purchase_payload"), dict) else {}
    order = create_order(
        {
            **purchase_payload,
            "confirmed": True,
            "payment_verified": True,
            "payment": {"order_id": order_id, "payment_id": payment_id},
        },
        user_id,
    )
    attempt["status"] = "paid"
    attempt["payment_id"] = payment_id[:120]
    attempt["order_id"] = order["id"]
    attempt["updated_at"] = now_iso()
    db.update_payment_attempt(attempt)
    return order
