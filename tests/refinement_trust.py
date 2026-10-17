"""A browser may choose products and preferences, but never invent purchase evidence."""

from __future__ import annotations

import tempfile
import sys
import unittest
import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import Database
from backend.orders import OrderError, canonical_order_preview, create_order
from backend.workflow import create_purchase_plan, run_refinement


class RefinementTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="artha-refine-", dir="/private/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Database(Path(directory.name) / "search.sqlite3")
        self.search_id = "search-trust-test"
        self.intent = {
            "category": "Clothing", "budget": 1200, "quantity": 1,
            "location": "Bengaluru", "arrive_by_days": 3,
            "raw_text": "A blue shirt", "description": "A blue shirt",
            "clarifications": [], "must_have": [],
        }
        self.product = {
            "id": "shirt", "name": "Blue shirt", "price": 900,
            "total_price": 900, "delivery_days": 2, "stock": 2,
            "url": "https://shop.example/shirt", "source_kind": "sandbox_catalog",
            "research_status": "complete", "features": ["shirt"],
        }
        self.database.save_search(self.search_id, "A blue shirt", self.intent, [], products=[self.product])
        workflow_db = patch("backend.workflow.db", self.database)
        orders_db = patch("backend.orders.db", self.database)
        workflow_db.start()
        orders_db.start()
        self.addCleanup(workflow_db.stop)
        self.addCleanup(orders_db.stop)

    def test_refinement_uses_saved_intent_product_and_source(self) -> None:
        result = run_refinement({
            "search_id": self.search_id, "text": "Prefer breathable",
            "intent": {**self.intent, "budget": 1},
            "products": [{**self.product, "price": 1, "total_price": 1}],
            "source": {"mode": "live", "research": {"mode": "parallel_url_scrape"}},
        })
        self.assertEqual(result["intent"]["budget"], 1200)
        self.assertEqual(result["products"][0]["price"], 900)
        self.assertEqual(result["source"]["mode"], "sandbox")
        self.assertEqual(self.database.get_search_products(result["search_id"])[0]["price"], 900)

    def test_refinement_rejects_forged_search_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "search"):
            run_refinement({
                "search_id": "search-forged", "text": "Prefer breathable",
                "intent": self.intent, "products": [self.product],
            })

    def test_refinement_cannot_reuse_another_users_taste(self) -> None:
        intent = {**self.intent, "_search_user_id": "alice", "_profile_user_id": "alice",
                  "taste_context": {"memories": [{"id": "private-memory"}]}}
        self.database.save_search(self.search_id, "A blue shirt", intent, [], products=[self.product])
        with self.assertRaisesRegex(ValueError, "account"):
            run_refinement({"search_id": self.search_id, "text": "Prefer breathable", "user_id": "bob"})
        result = run_refinement({"search_id": self.search_id, "text": "Prefer breathable", "user_id": "alice", "use_profile": False})
        self.assertNotIn("taste_context", result["intent"])

    def test_refinement_refreshes_retrieval_for_current_query(self) -> None:
        intent = {**self.intent, "_search_user_id": "alice", "_profile_user_id": "alice"}
        self.database.save_search(self.search_id, "A blue shirt", intent, [], products=[self.product])
        with patch("backend.taste_memory.retrieve_memories", return_value={"memories": [], "mode": "empty"}) as retrieve:
            result = run_refinement({"search_id": self.search_id, "text": "Prefer breathable", "user_id": "alice", "use_profile": True})
        self.assertEqual(retrieve.call_args.args[0], "alice")
        self.assertIn("Prefer breathable", retrieve.call_args.args[1])
        self.assertEqual(result["intent"]["taste_context"]["mode"], "empty")

    def test_plan_uses_saved_product_fields(self) -> None:
        plan = create_purchase_plan({
            "search_id": self.search_id,
            "products": [{"id": "shirt", "price": 1, "total_price": 1, "url": "https://evil.example"}],
        }, "user-test")
        self.assertEqual(plan["total"], 900)
        self.assertEqual(plan["items"][0]["url"], self.product["url"])

    def test_order_requires_a_saved_search_or_plan(self) -> None:
        with self.assertRaises(OrderError):
            canonical_order_preview({"confirmed": True, "products": [self.product]}, "user-test")

    def test_direct_order_cannot_claim_razorpay_verified(self) -> None:
        payload = {"confirmed": True, "search_id": self.search_id,
                   "products": [{"id": "shirt"}], "payment_verified": True}
        with patch("backend.orders.setting", return_value="razorpay"):
            with self.assertRaisesRegex(OrderError, "payment"):
                create_order(payload, "user-test")

    def test_old_plan_cannot_change_the_checkout_price(self) -> None:
        self.database.save_purchase_plan({
            "id": "plan-old", "user_id": "user-test", "search_id": self.search_id,
            "status": "ready_for_checkout", "total": 1,
            "items": [{**self.product, "price": 1, "total_price": 1}],
            "created_at": "2026-09-25T00:00:00+00:00", "updated_at": "2026-09-25T00:00:00+00:00",
        })
        preview = canonical_order_preview({"confirmed": True, "plan_id": "plan-old"}, "user-test")
        self.assertEqual(preview["total"], 900)

    def test_payment_verification_rejects_changed_search_total(self) -> None:
        from backend.payments import PaymentError, verify_payment

        with patch("backend.payments.db", self.database), \
             patch("backend.payments._require_razorpay", return_value=("key", "secret")):
            self.database.save_payment_attempt({
                "id": "pay-drift", "user_id": "user-test", "provider": "razorpay",
                "provider_order_id": "order-drift", "amount": 900, "currency": "INR",
                "status": "created", "created_at": "2026-09-25T00:00:00+00:00",
                "updated_at": "2026-09-25T00:00:00+00:00",
                "purchase_payload": {"confirmed": True, "search_id": self.search_id,
                                     "products": [{"id": "shirt"}]},
            })
            self.database.save_search(self.search_id, "A blue shirt", self.intent, [],
                                      products=[{**self.product, "price": 1000, "total_price": 1000}])
            signature = hmac.new(b"secret", b"order-drift|pay-drift", hashlib.sha256).hexdigest()
            with self.assertRaisesRegex(PaymentError, "total changed"):
                verify_payment({"razorpay_order_id": "order-drift", "razorpay_payment_id": "pay-drift",
                                "razorpay_signature": signature}, {"id": "user-test"})
            self.assertEqual(self.database.get_payment_attempt("order-drift", "user-test")["status"], "needs_review")

    def test_legacy_search_cannot_seed_new_purchase_evidence(self) -> None:
        with self.database._connect() as connection:
            connection.execute("UPDATE searches SET server_verified = 0 WHERE id = ?", (self.search_id,))
        self.assertEqual(self.database.get_search_products(self.search_id), [])
        with self.assertRaisesRegex(ValueError, "search|verified|trusted"):
            run_refinement({"search_id": self.search_id, "text": "Prefer breathable"})
        with self.assertRaises(ValueError):
            create_purchase_plan({"search_id": self.search_id, "products": [{"id": "shirt"}]}, "user-test")
        with self.assertRaises(OrderError):
            canonical_order_preview({"confirmed": True, "search_id": self.search_id,
                                     "products": [{"id": "shirt"}]}, "user-test")

    def test_only_one_payment_verifier_can_claim_an_attempt(self) -> None:
        self.database.save_payment_attempt({
            "id": "pay-race", "user_id": "user-test", "provider": "razorpay",
            "provider_order_id": "order-race", "amount": 900, "currency": "INR",
            "status": "created", "created_at": "2026-09-25T00:00:00+00:00",
            "updated_at": "2026-09-25T00:00:00+00:00",
        })
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(lambda _: self.database.claim_payment_attempt("order-race", "user-test"), range(2)))
        self.assertEqual(sum(attempt is not None for attempt in claimed), 1)


if __name__ == "__main__":
    unittest.main()
