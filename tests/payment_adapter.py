"""Offline contract test for the opt-in Razorpay adapter."""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="artha-payment-", dir="/private/tmp") as directory:
        os.environ.update(
            {
                "SHOPPINGHELP_DB_PATH": str(Path(directory) / "payment.sqlite3"),
                "SHOPPINGHELP_SEARCH_MODE": "fixture",
                "APP_ENV": "development",
                "PAYMENT_PROVIDER": "razorpay",
                "RAZORPAY_KEY_ID": "rzp_test_key",
                "RAZORPAY_KEY_SECRET": "test_secret",
            }
        )
        from backend.db import db
        import backend.payments as payments

        user = db.upsert_google_user(google_sub="payment-test", email="payment@example.test", name="Payment Test", picture="")
        search_id = "search-payment-test"
        db.save_search(
            search_id,
            "chair",
            {"location": "Bengaluru"},
            [],
            products=[{"id": "p1", "name": "Chair", "price": 1000, "total_price": 1000, "quantity": 1, "url": "https://store.example/chair", "delivery_days": 3}],
        )
        payments._razorpay_order = lambda amount, receipt, notes, key_id, key_secret: {"id": "order_test_123", "amount": amount * 100, "currency": "INR"}
        payment = payments.create_payment_order({"confirmed": True, "search_id": search_id, "products": [{"id": "p1"}], "location": "Bengaluru"}, user)
        assert payment["order_id"] == "order_test_123"
        signature = hmac.new(b"test_secret", b"order_test_123|pay_test_123", hashlib.sha256).hexdigest()
        order = payments.verify_payment(
            {"razorpay_order_id": "order_test_123", "razorpay_payment_id": "pay_test_123", "razorpay_signature": signature},
            user,
        )
        assert order["payment_provider"] == "razorpay"
        assert order["payment_status"] == "paid"
        assert order["total"] == 1000
        print("payment_adapter_ok", order["id"])


if __name__ == "__main__":
    main()
