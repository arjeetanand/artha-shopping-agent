"""Razorpay verification for historical attempts; new charges are disabled."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from .db import db, now_iso
from .orders import OrderError, canonical_order_preview, create_order
from .settings import is_production, setting


class PaymentError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def payment_status() -> dict[str, Any]:
    provider = setting("PAYMENT_PROVIDER", "sandbox").lower()
    configured = provider == "sandbox" and not is_production()
    return {
        "provider": provider,
        "configured": configured,
        "mode": "local sandbox" if configured else "disabled in production" if provider == "sandbox" else "unavailable until retailer fulfillment is connected",
    }


def _require_razorpay() -> tuple[str, str]:
    if setting("PAYMENT_PROVIDER", "sandbox").lower() != "razorpay":
        raise PaymentError("Razorpay checkout is not enabled for this environment.")
    key_id = setting("RAZORPAY_KEY_ID")
    key_secret = setting("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise PaymentError("Razorpay is selected but RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are missing.", 503)
    return key_id, key_secret


def create_payment_order(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    raise PaymentError("In-app payment is unavailable until retailer fulfillment is connected. Complete purchases with the retailer.", 503)


def verify_payment(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    _, key_secret = _require_razorpay()
    user_id = str(user.get("id") or "")
    order_id = str(payload.get("razorpay_order_id") or "").strip()
    payment_id = str(payload.get("razorpay_payment_id") or "").strip()
    signature = str(payload.get("razorpay_signature") or "").strip()
    if not order_id or not payment_id or not signature:
        raise PaymentError("Razorpay did not return a complete payment verification payload.")
    attempt = db.claim_payment_attempt(order_id, user_id)
    if not attempt:
        if db.get_payment_attempt(order_id, user_id):
            raise PaymentError("This payment attempt has already been completed or rejected.")
        raise PaymentError("Payment order not found for this signed-in user.", 404)
    expected = hmac.new(key_secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        attempt["status"] = "rejected"
        attempt["updated_at"] = now_iso()
        db.update_payment_attempt(attempt)
        raise PaymentError("Razorpay payment verification failed. No order was recorded.", 400)
    purchase_payload = attempt.get("purchase_payload") if isinstance(attempt.get("purchase_payload"), dict) else {}
    try:
        if canonical_order_preview(purchase_payload, user_id)["total"] != attempt["amount"]:
            raise PaymentError("The purchase total changed after payment started. No order was recorded.")
        order = create_order(
            {
                **purchase_payload,
                "confirmed": True,
                "payment": {"order_id": order_id, "payment_id": payment_id},
            },
            user_id,
            verified_payment=True,
        )
    except (OrderError, PaymentError):
        attempt["status"] = "needs_review"
        attempt["updated_at"] = now_iso()
        db.update_payment_attempt(attempt)
        raise
    attempt["status"] = "paid"
    attempt["payment_id"] = payment_id[:120]
    attempt["order_id"] = order["id"]
    attempt["updated_at"] = now_iso()
    db.update_payment_attempt(attempt)
    return order
