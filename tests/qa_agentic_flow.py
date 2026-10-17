"""Focused QA contracts for the next agentic shopping-flow increment.

These tests deliberately cover behavior that is not represented by the existing
offline contracts. A red test is a concrete implementation gap, not a reason to
weaken the contract to match the current behavior.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AgenticFlowContracts(unittest.TestCase):
    @staticmethod
    def _saved_search(intent: dict, products: list[dict], source: dict | None = None):
        from backend.db import db

        return patch.object(db, "get_search", return_value={
            "intent": intent, "products": products, "source": source or {"mode": "sandbox"}, "trusted": True,
        })

    def setUp(self) -> None:
        self.search_mode = patch.dict(
            os.environ,
            {"APP_ENV": "development", "SHOPPINGHELP_SEARCH_MODE": "fixture"},
            clear=False,
        )
        self.search_mode.start()
        self.addCleanup(self.search_mode.stop)

    def test_clarification_first_stops_before_retailer_discovery(self) -> None:
        """Ambiguous briefs must return a question state before catalog/live search."""
        from backend.db import db
        from backend.workflow import run_search

        with patch.object(db, "save_search"):
            result = run_search({"text": "I want a dress"})

        self.assertEqual(
            result.get("status"),
            "needs_clarification",
            "run_search should pause and ask for missing constraints before searching",
        )
        self.assertEqual(result.get("products"), [])
        self.assertTrue(result.get("clarifications"))

    def test_sparse_brief_does_not_display_invented_mission_facts(self) -> None:
        from backend.workflow import BriefAgent

        brief, _ = BriefAgent().run({"text": "I need an office chair"})
        self.assertIsNone(brief["budget"])
        self.assertIsNone(brief["location"])
        self.assertIsNone(brief["arrive_by_days"])
        self.assertIsNone(brief["arrive_by"])
        self.assertIsNone(brief["mission"]["budget"])
        self.assertEqual({item["key"] for item in brief["clarifications"]}, {"budget", "location", "delivery"})

        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}):
            agent = BriefAgent()
            with patch.object(agent.model, "extract_brief", return_value=({"budget": 18000, "location": "Bengaluru", "arrive_by_days": 5, "category": "Office chair"}, "gemini")), \
                    patch.object(agent.model, "status", return_value={"configured": True}):
                brief, _ = agent.run({"text": "I need an office chair"})
        self.assertIsNone(brief["budget"])
        self.assertIsNone(brief["location"])
        self.assertIsNone(brief["arrive_by_days"])
        self.assertEqual({item["key"] for item in brief["clarifications"]}, {"budget", "location", "delivery"})

    def test_spoken_amount_and_model_deadline_are_grounded_in_the_request(self) -> None:
        from backend.workflow import BriefAgent, _merge_refinement_intent, _parse_budget

        self.assertEqual(_parse_budget("Under four thousand rupees"), 4000)
        self.assertEqual(_parse_budget("Five thousand rupees"), 5000)
        self.assertIsNone(_parse_budget("Deliver under 5 days"))
        self.assertIsNone(_parse_budget("2 chairs in 5 days"))
        clarified = _merge_refinement_intent({"budget": None, "clarifications": [{"key": "budget", "question": "Maximum spend?"}]}, "5000")
        self.assertEqual(clarified["budget"], 5000)
        self.assertEqual(clarified["clarifications"], [])
        text = "I need a dress in medium for a party. I can spend five thousand rupees and need it next Monday in Delhi"
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}):
            agent = BriefAgent()
            with patch.object(agent.model, "extract_brief", return_value=({"budget": 5000, "location": "Delhi", "arrive_by_days": 3, "category": "Clothing"}, "gemini")), \
                    patch.object(agent.model, "status", return_value={"configured": True}):
                brief, _ = agent.run({"text": text})
        self.assertEqual(brief["budget"], 5000)
        self.assertEqual(brief["location"], "Delhi")
        self.assertEqual(brief["arrive_by_days"], 3)

    def test_written_delivery_duration_is_parsed_without_becoming_location(self) -> None:
        """Natural-language durations must not fall through to the location parser."""
        from backend.workflow import BriefAgent

        brief, _event = BriefAgent().run(
            {"text": "A cool dress under ₹1,000 delivered in three days"}
        )

        self.assertEqual(brief.get("arrive_by_days"), 3)
        self.assertEqual(brief.get("budget"), 1000)
        self.assertNotIn("three days", str(brief.get("location") or "").lower())

    def test_missing_color_and_size_are_explicit_clarifications(self) -> None:
        """Fashion searches need variant questions when color and size are absent."""
        from backend.workflow import BriefAgent

        brief, _event = BriefAgent().run(
            {"text": "A dress under ₹1,000 delivered to Bengaluru within 3 days"}
        )
        clarification_keys = {
            str(item.get("key"))
            for item in brief.get("clarifications", [])
            if isinstance(item, dict)
        }

        self.assertIn("color", clarification_keys)
        self.assertIn("size", clarification_keys)

    def test_explicit_color_and_size_become_first_class_intent_fields(self) -> None:
        """Clear variant constraints must survive brief extraction as structured data."""
        from backend.workflow import BriefAgent

        brief, _event = BriefAgent().run(
            {
                "text": "A red medium dress under ₹1,000 delivered to Bengaluru within 3 days"
            }
        )

        self.assertEqual(brief.get("color"), "red")
        self.assertEqual(str(brief.get("size") or "").lower(), "medium")

    def test_follow_up_updates_color_and_size_and_resolves_questions(self) -> None:
        """A follow-up answer must update variant fields rather than only append prose."""
        from backend.db import db
        from backend.workflow import run_refinement

        previous_intent = {
            "category": "Clothing",
            "budget": 1000,
            "quantity": 1,
            "location": "Bengaluru",
            "arrive_by_days": 3,
            "arrive_by": "within 3 days",
            "must_have": [],
            "specifications": [],
            "nice_to_have": [],
            "raw_text": "a dress under ₹1,000",
            "description": "a dress",
            "clarifications": [
                {"key": "color", "question": "Which color?"},
                {"key": "size", "question": "Which size?"},
            ],
        }
        product = {
            "id": "qa-dress-1",
            "name": "Everyday Dress",
            "category": "Clothing",
            "brand": "QA Label",
            "seller": "QA Label",
            "url": "https://retailer.example/dress",
            "price": 900,
            "shipping_cost": 0,
            "total_price": 900,
            "delivery_days": 3,
            "delivery_label": "Arrives in 3 days",
            "stock": 4,
            "features": ["dress"],
        }

        with self._saved_search(previous_intent, [product]), patch.object(db, "save_search"):
            result = run_refinement(
                {
                    "search_id": "search-test",
                    "text": "Show me red options in size M",
                }
            )

        self.assertEqual(result["intent"].get("color"), "red")
        self.assertEqual(str(result["intent"].get("size") or "").lower(), "m")
        remaining_keys = {
            str(item.get("key"))
            for item in result["intent"].get("clarifications", [])
            if isinstance(item, dict)
        }
        self.assertNotIn("color", remaining_keys)
        self.assertNotIn("size", remaining_keys)

    def test_pincode_is_preserved_as_a_delivery_constraint(self) -> None:
        """A typed six-digit pincode must be retained for delivery verification."""
        from backend.workflow import BriefAgent

        brief, _event = BriefAgent().run(
            {
                "text": "A dress under ₹1,000 within 3 days",
                "location": "Bengaluru",
                "pincode": "560001",
            }
        )

        self.assertEqual(brief.get("pincode"), "560001")

    def test_mission_normalizes_date_and_variant_constraints(self) -> None:
        """A typed mission must become a date-only, structured brief before search."""
        from backend.workflow import BriefAgent, _india_today

        arrive_by_date = (_india_today() + timedelta(days=3)).isoformat()
        brief, _event = BriefAgent().run(
            {
                "text": "A linen overshirt",
                "mission": {
                    "occasion": "Wedding guest",
                    "arrive_by_date": arrive_by_date,
                    "budget": 4000,
                    "pincode": "560001",
                    "size": "M",
                    "color": "neutral",
                    "style": "summer",
                },
            }
        )

        self.assertEqual(brief["mission"]["arrive_by_date"], arrive_by_date)
        self.assertEqual(brief["arrive_by_days"], 3)
        self.assertEqual(brief["pincode"], "560001")
        self.assertEqual(brief["size"], "M")
        self.assertEqual(brief["color"], "neutral")
        self.assertFalse(brief["clarifications"])

    def test_fashion_brief_keeps_only_requested_requirements(self) -> None:
        from backend.workflow import BriefAgent

        brief, _ = BriefAgent().run({"text": "A red saree under ₹4,000 delivered to Bengaluru within 3 days", "pincode": "560001"})

        self.assertEqual(brief["category"], "Clothing")
        self.assertNotIn("neutral palette", brief["must_have"])

    def test_ranking_checks_requested_variant_combination(self) -> None:
        from backend.workflow import RankingAgent, _mission_decision

        product = {
            "id": "two-variants", "name": "Linen shirt", "price": 1000,
            "delivery_days": 2, "stock": 3, "features": ["linen"],
            "variants": [
                {"color": "red", "size": "S", "available": True, "stock": 2},
                {"color": "blue", "size": "M", "available": True, "stock": 1},
            ],
        }
        brief = {"budget": 2000, "arrive_by_days": 3, "color": "red", "size": "M", "fabric": "linen", "must_have": []}
        ranked, _ = RankingAgent().run([product], brief)

        self.assertFalse(ranked[0]["variant_fit"])
        self.assertFalse(ranked[0]["eligible"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

    def test_requested_variant_price_controls_budget_and_decision(self) -> None:
        from backend.workflow import RankingAgent, ResearchAgent, _mission_decision

        product = {"id": "shirt", "name": "Acme Shirt", "url": "https://shop.example/shirt",
                   "price": 900, "source_kind": "live_web"}
        brief = {"budget": 1000, "arrive_by_days": 3, "color": "red", "size": "M", "must_have": []}
        direct_page = {"pageType": "productDetail", "name": "Acme Shirt", "price": 900,
                       "shipping_cost": 0, "delivery_days": 2, "stock": 2,
                       "variants": [{"color": "red", "size": "M", "available": True, "stock": 2, "price": 2000}]}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": direct_page}):
            checked, complete = agent._one(product)
        self.assertTrue(complete)
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertEqual(ranked[0]["price"], 2000)
        self.assertEqual(ranked[0]["line_total"], 2000)
        self.assertFalse(ranked[0]["budget_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

        direct_page["variants"][0].pop("price")
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": direct_page}):
            checked, complete = agent._one(product)
        self.assertTrue(complete)
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertIsNone(ranked[0]["budget_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "verify_before_buy")

        for ambiguous_price in ("From ₹1,500", "₹1,500–₹2,000"):
            direct_page["variants"][0]["price"] = ambiguous_price
            with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": direct_page}):
                checked, complete = agent._one(product)
            self.assertTrue(complete)
            ranked, _ = RankingAgent().run([checked], brief)
            self.assertIsNone(ranked[0]["budget_fit"])
            self.assertEqual(_mission_decision(ranked, brief)["status"], "verify_before_buy")

    def test_sold_count_is_not_available_stock(self) -> None:
        from backend.workflow import RankingAgent, _mission_decision

        product = {"id": "shirt", "name": "Acme Shirt", "url": "https://shop.example/shirt",
                   "price": 900, "delivery_days": 2, "stock": "100 sold", "source_kind": "live_web",
                   "research_status": "complete", "price_verification": "matched", "shipping_verified": True}
        brief = {"budget": 1000, "arrive_by_days": 3, "must_have": []}
        ranked, _ = RankingAgent().run([product.copy()], brief)
        self.assertIsNone(ranked[0]["stock_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "verify_before_buy")
        for stock in (2, "2 in stock", "2 available"):
            ranked, _ = RankingAgent().run([{**product, "stock": stock}], brief)
            self.assertTrue(ranked[0]["stock_fit"])

    def test_fabric_in_features_clears_fabric_requirement(self) -> None:
        from backend.workflow import RankingAgent, _mission_decision

        product = {"id": "linen", "name": "Summer shirt", "price": 1000, "currency": "INR", "delivery_days": 2, "stock": 2,
                   "features": ["100% linen"], "research_status": "complete", "url": "https://shop.example/linen"}
        brief = {"budget": 2000, "arrive_by_days": 3, "fabric": "linen", "must_have": []}

        ranked, _ = RankingAgent().run([product], brief)

        self.assertTrue(ranked[0]["fabric_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "buy_now")

    def test_direct_price_replaces_stale_extraction_total(self) -> None:
        from backend.workflow import ExtractionAgent, RankingAgent, ResearchAgent, _mission_decision

        product = ExtractionAgent()._from_live({"title": "Acme Widget X1", "url": "https://shop.example/x1",
                                                "data": {"name": "Acme Widget X1", "shipping_cost": 100}}, 0)
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "name": "Acme Widget X1", "price": 1000, "stock": 2, "delivery_days": 2, "shipping_cost": 100,
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)

        brief = {"budget": 200, "arrive_by_days": 3, "must_have": []}
        ranked, _ = RankingAgent().run([checked], brief)

        self.assertEqual(ranked[0]["line_total"], 1100)
        self.assertFalse(ranked[0]["budget_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

    def test_direct_shipping_replaces_unverified_search_shipping(self) -> None:
        from backend.workflow import ExtractionAgent, RankingAgent, ResearchAgent

        product = ExtractionAgent()._from_live({"title": "Acme Widget X1", "url": "https://shop.example/x1",
                                                "data": {"name": "Acme Widget X1", "price": 1000}}, 0)
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "name": "Acme Widget X1", "price": 1000, "shipping_cost": 100, "stock": 2,
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)

        ranked, _ = RankingAgent().run([checked], {"budget": 1050, "must_have": []})

        self.assertEqual(ranked[0]["line_total"], 1100)
        self.assertFalse(ranked[0]["budget_fit"])

    def test_missing_direct_currency_cannot_create_a_price_observation(self) -> None:
        from backend.price_history import verified_price_offer
        from backend.workflow import ExtractionAgent, ResearchAgent

        product = ExtractionAgent()._from_live({
            "title": "Acme Widget X1", "url": "https://shop.example/products/x1",
            "data": {"name": "Acme Widget X1", "price": 1000},
        }, 0)
        self.assertIsNone(product["currency"])
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Widget X1", "price": 1000,
            "stock": 2, "delivery_days": 2, "shipping_cost": 0,
        }}):
            checked, completed = agent._one(product)

        self.assertTrue(completed)
        self.assertIsNone(checked["currency"])
        self.assertEqual(checked["price_verification"], "currency_unknown")
        self.assertIsNone(verified_price_offer(checked, "url:https://shop.example/products/x1", "2026-09-25T00:00:00Z"))

    def test_direct_page_replaces_or_clears_search_seller_and_brand_claims(self) -> None:
        from backend.workflow import ResearchAgent

        product = {"id": "chair", "name": "Acme Office Chair", "url": "https://shop.example/products/chair",
                   "price": 1000, "currency": "INR", "brand": "Fake Brand", "seller": "Fake Seller",
                   "seller_reliability": 0.99, "source_kind": "live_web"}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Office Chair", "price": 1000,
            "currency": "INR", "brand": "Acme", "seller": "Real Seller", "seller_reliability": 0.42,
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        self.assertEqual((checked["brand"], checked["seller"], checked["seller_reliability"]),
                         ("Acme", "Real Seller", 0.42))

        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Office Chair", "price": 1000, "currency": "INR",
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        self.assertIsNone(checked["brand"])
        self.assertEqual(checked["seller"], "shop.example")
        self.assertIsNone(checked["seller_reliability"])

    def test_direct_price_ranges_and_from_prices_are_not_exact_quotes(self) -> None:
        from backend.price_history import verified_price_offer
        from backend.workflow import ResearchAgent

        product = {"id": "chair", "name": "Acme Office Chair", "url": "https://shop.example/products/chair",
                   "price": 1000, "currency": "INR", "source_kind": "live_web"}
        agent = ResearchAgent()
        for quote in ("From ₹1,000", "₹1,000 - ₹1,500", "₹1,000/month"):
            with self.subTest(quote=quote), patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
                "pageType": "productDetail", "name": "Acme Office Chair", "price": quote, "currency": "INR",
            }}):
                checked, completed = agent._one(product)
                self.assertTrue(completed)
                self.assertIsNone(checked.get("price_verification"))
                self.assertIsNone(verified_price_offer(checked, "url:https://shop.example/products/chair", "2026-09-25T00:00:00Z"))

        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Office Chair", "price": "₹1,000", "currency": "INR",
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        self.assertEqual(checked["price_verification"], "matched")

    def test_direct_page_conflicts_replace_stale_listing_claims(self) -> None:
        from backend.workflow import RankingAgent, ResearchAgent, _mission_decision

        product = {
            "id": "chair", "name": "Acme Office Chair", "url": "https://shop.example/chair",
            "price": 1000, "total_price": 1000, "delivery_days": 2, "stock": 2,
            "rating": 4.9, "source_kind": "live_web",
        }
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Office Chair", "price": 1500,
            "currency": "INR", "rating": 3.2, "delivery_days": 10, "stock": 0,
        }}):
            checked, completed = agent._one(product)

        self.assertTrue(completed)
        self.assertEqual(checked["price"], 1500)
        self.assertEqual(checked["total_price"], 1500)
        self.assertEqual(checked["delivery_days"], 10)
        self.assertEqual(checked["stock"], 0)
        self.assertEqual(checked["rating"], 3.2)
        self.assertEqual(checked["price_verification"], "mismatch")
        self.assertEqual(checked["direct_page_price"], 1500)
        brief = {"budget": 1200, "arrive_by_days": 3, "must_have": []}
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertFalse(ranked[0]["budget_fit"])
        self.assertFalse(ranked[0]["delivery_fit"])
        self.assertFalse(ranked[0]["stock_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Office Chair", "price": 1000, "currency": "INR",
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        self.assertIsNone(checked["delivery_days"])
        self.assertIsNone(checked["stock"])
        self.assertIsNone(checked["rating"])
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertEqual(_mission_decision(ranked, brief)["status"], "verify_before_buy")

    def test_direct_variants_replace_stale_listing_availability(self) -> None:
        from backend.workflow import RankingAgent, ResearchAgent, _mission_decision

        product = {"id": "shirt", "name": "Acme Shirt", "url": "https://shop.example/shirt",
                   "price": 1000, "delivery_days": 2, "stock": 2, "source_kind": "live_web",
                   "colors": ["blue"], "sizes": ["M"],
                   "variants": [{"color": "blue", "size": "M", "available": True, "stock": 2}]}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Shirt", "price": 1000,
            "delivery_days": 2, "stock": 2, "colors": ["blue"], "sizes": ["M"],
            "variants": [{"color": "blue", "size": "M", "available": False, "stock": 0}],
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        brief = {"budget": 2000, "arrive_by_days": 3, "color": "blue", "size": "M", "must_have": []}
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertFalse(ranked[0]["variant_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

    def test_material_mentions_do_not_confirm_requested_fabric(self) -> None:
        from backend.workflow import RankingAgent, ResearchAgent, _mission_decision

        product = {"id": "shirt", "name": "Linen-look Overshirt", "url": "https://shop.example/shirt",
                   "description": "100% polyester; linen-look weave, contains no linen", "price": 1000,
                   "delivery_days": 2, "stock": 2, "source_kind": "live_web"}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Linen-look Overshirt", "price": 1000,
            "delivery_days": 2, "stock": 2, "material": "polyester",
            "features": ["100% polyester", "linen-look weave, contains no linen"],
        }}):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        brief = {"budget": 2000, "arrive_by_days": 3, "fabric": "linen", "must_have": ["linen"]}
        ranked, _ = RankingAgent().run([checked], brief)
        self.assertIsNot(ranked[0]["fabric_fit"], True)
        self.assertIsNot(ranked[0]["must_have_fit"], True)
        self.assertNotEqual(_mission_decision(ranked, brief)["status"], "buy_now")

    def test_accessory_page_does_not_verify_product(self) -> None:
        from backend.workflow import ResearchAgent

        agent = ResearchAgent()
        product = {"id": "phone", "name": "Acme Widget X1", "url": "https://shop.example/case", "price": 1000}
        with patch.object(agent.client, "scrape_inline", return_value={"generatedJson": {
            "name": "Acme Widget X1 Case", "price": 1000, "stock": 2,
        }}):
            checked, completed = agent._one(product)

        self.assertFalse(completed)
        self.assertNotEqual(checked.get("price_verification"), "matched")

    def test_direct_product_title_can_omit_store_suffix_but_listing_cannot_verify(self) -> None:
        from backend.workflow import ResearchAgent

        agent = ResearchAgent()
        product = {"id": "chair", "name": "SIHOO M102C Ergonomic Office Chair – Store Name", "url": "https://shop.example/products/m102c", "price": 1000}
        direct = {"generatedJson": {"pageType": "productDetail", "name": "SIHOO M102C Ergonomic Office Chair", "price": 1000, "currency": "Rs."}}
        with patch.object(agent.client, "scrape_inline", return_value=direct):
            checked, completed = agent._one(product)
        self.assertTrue(completed)
        self.assertEqual(checked["price_verification"], "matched")
        self.assertEqual(checked["currency"], "INR")

        wrapped = {"id": "caper", "name": "Buy Caper High Back Mesh Office Chair (Black) @33% OFF Online | Wooden Street", "url": "https://shop.example/product/caper", "price": 7999}
        direct = {"generatedJson": {"pageType": "productDetail", "name": "Caper High Back Mesh Office Chair (Black)", "price": 7999, "currency": "INR"}}
        with patch.object(agent.client, "scrape_inline", return_value=direct):
            checked, completed = agent._one(wrapped)
        self.assertTrue(completed)
        self.assertEqual(checked["name"], "Caper High Back Mesh Office Chair (Black)")
        self.assertEqual(checked["price_verification"], "matched")

        listing = {"generatedJson": {"pageType": "productListing", "name": "SIHOO M102C Ergonomic Office Chair", "price": 1000}}
        with patch.object(agent.client, "scrape_inline", return_value=listing):
            _, completed = agent._one(product)
        self.assertFalse(completed)

    def test_refinement_applies_visible_mission_changes(self) -> None:
        from backend.db import db
        from backend.workflow import _india_today, run_refinement

        deadline = (_india_today() + timedelta(days=1)).isoformat()
        previous = {"category": "Clothing", "budget": 1200, "arrive_by_days": 3, "arrive_by": "within 3 days",
                    "color": "blue", "size": "M", "pincode": "560001", "location": "Bengaluru",
                    "raw_text": "Blue shirt", "description": "Blue shirt", "clarifications": [], "must_have": []}
        product = {"id": "shirt", "name": "Blue shirt", "price": 900, "delivery_days": 2, "stock": 2,
                   "colors": ["blue"], "sizes": ["M"], "url": "https://shop.example/shirt", "research_status": "complete"}
        mission = {"budget": 800, "arrive_by_date": deadline, "color": "red", "size": "M", "pincode": "560001"}

        with self._saved_search(previous, [product]), patch.object(db, "save_search"):
            result = run_refinement({"search_id": "search-test", "text": "Please refine", "mission": mission})

        self.assertEqual(result["intent"]["budget"], 800)
        self.assertEqual(result["intent"]["arrive_by_days"], 1)
        self.assertEqual(result["intent"]["color"], "red")
        self.assertEqual(result["intent"]["mission"]["arrive_by_date"], deadline)
        self.assertEqual(result["intent"]["decision"]["status"], "no_safe_fit")

    def test_hard_refinement_rediscovers_when_old_shortlist_has_no_fit(self) -> None:
        from backend.db import db
        from backend.workflow import SearchAgent, run_refinement

        previous = {"category": "Clothing", "budget": 1200, "arrive_by_days": 3, "arrive_by": "within 3 days",
                    "color": "blue", "size": "M", "pincode": "560001", "location": "Bengaluru",
                    "raw_text": "Blue shirt", "description": "Blue shirt", "clarifications": [], "must_have": []}
        old_product = {"id": "blue", "name": "Blue shirt", "price": 900, "delivery_days": 2, "stock": 2,
                       "colors": ["blue"], "sizes": ["M"], "url": "https://shop.example/blue"}
        new_source = {"id": "red", "title": "Red shirt", "url": "https://shop.example/red", "source_kind": "sandbox_catalog",
                      "data": {"name": "Red shirt", "price": 950, "delivery_days": 2, "stock": 2,
                               "colors": ["red"], "sizes": ["M"],
                               "variants": [{"color": "red", "size": "M", "available": True, "stock": 2}]}}
        with self._saved_search(previous, [old_product]), patch.object(db, "save_search"), patch.object(SearchAgent, "run", return_value=(
            [new_source], {"agent": "Search agent", "status": "complete", "detail": "New source"}, {"mode": "sandbox"},
        )) as search:
            result = run_refinement({"search_id": "search-test", "text": "Find red instead", "mission": {"color": "red"}})

        search.assert_called_once()
        self.assertEqual(search.call_args.args[0]["color"], "red")
        self.assertEqual(result["intent"]["decision"]["recommended_product_id"], "red")
        self.assertEqual(result["products"][0]["id"], "red")

    def test_destination_edit_researches_delivery_for_new_destination(self) -> None:
        from backend.db import db
        from backend.workflow import SearchAgent, run_refinement

        previous = {"category": "Electronics", "budget": 1200, "arrive_by_days": 3,
                    "pincode": "560001", "location": "Bengaluru", "raw_text": "Tablet",
                    "description": "Tablet", "clarifications": [], "must_have": []}
        old_product = {"id": "old-pin", "name": "Tablet", "price": 900, "delivery_days": 2,
                       "stock": 2, "url": "https://shop.example/old", "research_status": "complete",
                       "delivery_pincode": "560001"}
        fresh_source = {"id": "fresh-pin", "title": "Tablet", "url": "https://shop.example/fresh",
                        "source_kind": "sandbox_catalog", "data": {"name": "Tablet", "price": 900,
                        "delivery_days": 2, "stock": 2}}
        edits = (
            ("changed pincode", {"text": "Update delivery destination", "mission": {"pincode": "110001"}}, "110001", "Bengaluru"),
            ("cleared pincode", {"text": "Update delivery destination", "mission": {"pincode": ""}}, None, "Bengaluru"),
            ("changed city", {"text": "Deliver to Delhi"}, None, "Delhi"),
        )
        for label, edit, pincode, location in edits:
            with self.subTest(edit=label), self._saved_search(previous, [old_product]), \
                    patch.object(db, "save_search"), patch.object(SearchAgent, "run", return_value=(
                        [fresh_source], {"agent": "Search agent", "status": "complete", "detail": "Fresh"},
                        {"mode": "sandbox"},
                    )) as search:
                result = run_refinement({"search_id": "search-test", **edit})
                search.assert_called_once()
                self.assertEqual(result["products"][0]["id"], "fresh-pin")
                self.assertEqual(search.call_args.args[0].get("pincode"), pincode)
                self.assertEqual(search.call_args.args[0].get("location"), location)

        with self._saved_search({**previous, "category": "Clothing"}, [old_product]), \
                patch.object(db, "save_search"), patch.object(SearchAgent, "run") as search:
            result = run_refinement({"search_id": "search-test", "text": "Deliver to Delhi"})
            search.assert_not_called()
            self.assertEqual(result["status"], "needs_clarification")
            self.assertEqual(result["products"], [])
            self.assertIn("pincode", {item["key"] for item in result["clarifications"]})

    def test_refinement_can_clear_a_visible_optional_constraint(self) -> None:
        from backend.db import db
        from backend.workflow import SearchAgent, run_refinement

        previous = {"category": "Clothing", "budget": 1200, "arrive_by_days": 3, "color": "blue", "pincode": "560001",
                    "raw_text": "Blue shirt", "description": "Blue shirt", "clarifications": [], "must_have": []}
        product = {"id": "shirt", "name": "Blue shirt", "price": 900, "delivery_days": 2, "stock": 2,
                   "colors": ["blue"], "source_kind": "sandbox_catalog", "url": "https://shop.example/shirt",
                   "research_status": "complete"}
        with self._saved_search(previous, [product]), patch.object(db, "save_search"), patch.object(SearchAgent, "run") as search:
            result = run_refinement({"search_id": "search-test", "text": "Any color is fine", "mission": {"color": ""}})

        search.assert_not_called()
        self.assertIsNone(result["intent"]["color"])
        self.assertIsNone(result["intent"]["mission"]["color"])
        self.assertIsNone(result["products"][0]["color_fit"])

    def test_buy_now_requires_direct_research(self) -> None:
        from backend.workflow import _mission_decision

        product = {
            "id": "search-only", "eligible": True, "budget_fit": True,
            "delivery_fit": True, "stock_fit": True, "price": 1200,
            "research_status": "waiting",
        }
        decision = _mission_decision([product], {})

        self.assertEqual(decision["status"], "verify_before_buy")
        self.assertIn("product page", " ".join(decision["blocking_risks"]).lower())

    def test_decision_gate_covers_buy_verify_and_no_safe_fit(self) -> None:
        """Unknown purchase facts must block Buy now even after ranking has found a fit."""
        from backend.workflow import _mission_decision

        ready = {
            "id": "ready",
            "name": "Ready option",
            "eligible": True,
            "budget_fit": True,
            "delivery_fit": True,
            "stock_fit": True,
            "color_fit": True,
            "size_fit": True,
            "variant_fit": True,
            "price": 1200,
            "currency": "INR",
            "currency_fit": True,
            "url": "https://retailer.example/ready",
            "research_status": "complete",
            "source_kind": "sandbox_catalog",
            "reason_tags": ["Within budget", "Within delivery window"],
        }
        buy_now = _mission_decision([ready], {"color": "blue", "size": "M"})
        self.assertEqual(buy_now["status"], "buy_now")
        self.assertEqual(buy_now["recommended_product_id"], "ready")

        unknown_stock = {**ready, "id": "unknown-stock", "stock_fit": None}
        verify = _mission_decision([unknown_stock], {"color": "blue", "size": "M"})
        self.assertEqual(verify["status"], "verify_before_buy")
        self.assertIn("Stock", " ".join(verify["blocking_risks"]))

        no_fit = _mission_decision([{**ready, "id": "late", "eligible": False, "delivery_fit": False}], {})
        self.assertEqual(no_fit["status"], "no_safe_fit")
        self.assertIsNone(no_fit["recommended_product_id"])

    def test_no_fit_change_mentions_every_required_relaxation(self) -> None:
        from backend.workflow import _mission_decision

        decision = _mission_decision([
            {"id": "chair-a", "eligible": False, "budget_fit": False, "delivery_fit": False, "match_score": 80},
            {"id": "chair-b", "eligible": False, "budget_fit": False, "delivery_fit": False, "match_score": 70},
        ], {})
        self.assertEqual(decision["status"], "no_safe_fit")
        self.assertIn("budget", decision["mission_change"].lower())
        self.assertIn("arrival date", decision["mission_change"].lower())

    def test_decision_only_names_a_real_second_eligible_fallback(self) -> None:
        """A fallback is useful only when a second source has no known hard failure."""
        from backend.workflow import _mission_decision

        ready = {
            "id": "ready",
            "eligible": True,
            "budget_fit": True,
            "delivery_fit": True,
            "stock_fit": True,
            "price": 1200,
            "research_status": "complete",
            "reason_tags": [],
        }
        self.assertIsNone(_mission_decision([ready], {})["fallback_product_id"])
        fallback = {**ready, "id": "fallback", "price": 1300}
        self.assertEqual(_mission_decision([ready, fallback], {})["fallback_product_id"], "fallback")

    def test_directly_verified_fit_beats_unverified_cheaper_listing(self) -> None:
        from backend.workflow import _mission_decision

        listing = {"id": "listing", "eligible": True, "match_score": 95, "price": 900,
                   "source_kind": "live_web", "url": "https://a.example/chair", "research_status": "waiting",
                   "budget_fit": True, "delivery_fit": True, "stock_fit": True}
        checked = {**listing, "id": "checked", "price": 1000, "currency": "INR", "currency_fit": True, "match_score": 88,
                   "url": "https://b.example/chair", "research_status": "complete", "price_verification": "matched",
                   "shipping_verified": True, "shipping_cost": 0}
        decision = _mission_decision([listing, checked], {})
        self.assertEqual(decision["status"], "buy_now")
        self.assertEqual(decision["recommended_product_id"], "checked")

    def test_live_purchase_gate_requires_direct_shipping_cost(self) -> None:
        from backend.workflow import _mission_decision

        product = {"id": "chair", "eligible": True, "price": 1000, "currency": "INR", "currency_fit": True, "source_kind": "live_web",
                   "url": "https://shop.example/chair", "research_status": "complete",
                   "price_verification": "matched", "budget_fit": True, "delivery_fit": True,
                   "stock_fit": True}
        decision = _mission_decision([product], {})
        self.assertEqual(decision["status"], "verify_before_buy")
        self.assertIn("Shipping", " ".join(decision["blocking_risks"]))
        self.assertEqual(_mission_decision([{**product, "shipping_verified": True}], {})["status"], "buy_now")

    def test_refinement_recomputes_decision_without_researching_sources(self) -> None:
        """Talk-to-Artha changes must reuse completed evidence and return a new decision."""
        from backend.db import db
        from backend.workflow import SearchAgent, run_refinement

        product = {
            "id": "qa-ready-1",
            "name": "Ready overshirt",
            "category": "Clothing",
            "seller": "QA retailer",
            "url": "https://retailer.example/overshirt",
            "price": 900,
            "currency": "INR",
            "total_price": 900,
            "delivery_days": 2,
            "stock": 3,
            "colors": ["blue"],
            "sizes": ["m"],
            "variants": [{"color": "blue", "size": "m", "available": True, "stock": 3}],
            "features": ["linen", "breathable"],
            "research_status": "complete",
        }
        intent = {
            "category": "Clothing",
            "budget": 1200,
            "quantity": 1,
            "location": "Bengaluru",
            "arrive_by_days": 3,
            "arrive_by": "within 3 days",
            "pincode": "560001",
            "color": "blue",
            "size": "m",
            "must_have": ["linen"],
            "specifications": ["linen"],
            "nice_to_have": [],
            "raw_text": "A blue linen overshirt",
            "description": "A blue linen overshirt",
            "clarifications": [],
        }

        with self._saved_search(intent, [product]), patch.object(db, "save_search"), patch.object(SearchAgent, "run") as search:
            result = run_refinement(
                {"search_id": "search-test", "text": "Make it more summer"}
            )

        search.assert_not_called()
        self.assertEqual(result["intent"]["decision"]["status"], "buy_now")

    def test_cheaper_follow_up_changes_the_recommended_option(self) -> None:
        from backend.db import db
        from backend.workflow import SearchAgent, run_refinement

        intent = {"category": "Office chair", "budget": 2000, "arrive_by_days": 3,
                  "brand": "Acme", "must_have": [], "nice_to_have": [], "clarifications": [],
                  "raw_text": "An office chair", "description": "An office chair"}
        common = {"name": "Office chair", "delivery_days": 2, "stock": 2,
                  "research_status": "complete", "source_kind": "sandbox_catalog"}
        products = [
            {**common, "id": "preferred", "brand": "Acme", "price": 1500, "url": "https://a.example/chair"},
            {**common, "id": "cheaper", "brand": "Other", "price": 1000, "url": "https://b.example/chair"},
        ]
        with self._saved_search(intent, products), patch.object(db, "save_search"), patch.object(SearchAgent, "run") as search:
            result = run_refinement({"search_id": "search-test", "text": "Find me a cheaper alternative"})
        search.assert_not_called()
        self.assertEqual(result["intent"]["decision"]["recommended_product_id"], "cheaper")

    def test_empty_direct_retailer_page_is_not_verified(self) -> None:
        """An empty scrape must remain unverified instead of becoming direct evidence."""
        from backend.workflow import ResearchAgent

        agent = ResearchAgent()
        product = {
            "id": "qa-live-1",
            "name": "Retailer result",
            "url": "https://retailer.example/item",
            "price": 900,
            "total_price": 900,
            "features": [],
        }
        with patch.object(agent.client, "scrape_inline", return_value={}):
            enriched, completed = agent._one(product)

        self.assertFalse(completed)
        self.assertNotEqual(enriched.get("research_status"), "complete")

    def test_research_checks_product_urls_before_listing_urls(self) -> None:
        """Late product pages must get a direct check before the four-page cap is spent."""
        from backend.workflow import ResearchAgent

        agent = ResearchAgent()
        products = [
            {
                "id": str(index),
                "name": f"Option {index}",
                "url": (
                    f"https://merchant.example/products/sku-{index}" if index == 7 else
                    f"https://merchant.example/other/p/sku-{index}" if index == 9 else
                    f"https://merchant.example/collections/category-{index}"
                ),
            }
            for index in range(10)
        ]

        def scrape(url: str, max_wait_seconds: int = 90) -> dict:
            if "/products/" in url or "/p/" in url:
                index = int(url.rsplit("-", 1)[-1])
                return {"generatedJson": {"name": f"Option {index}", "price": 900}}
            return {}

        with patch.object(agent.client, "scrape_inline", side_effect=scrape) as scraper:
            enriched, event, source = agent.run(products, {"mode": "live"})

        checked = {call.args[0] for call in scraper.call_args_list}
        self.assertEqual(source["research"], {"mode": "parallel_url_scrape", "attempted": 4, "completed": 2})
        self.assertEqual(event["status"], "complete")
        self.assertEqual([product["id"] for product in enriched], [str(index) for index in range(10)])
        self.assertEqual({enriched[index]["research_status"] for index in (7, 9)}, {"complete"})
        self.assertEqual(checked, {products[index]["url"] for index in (0, 1, 7, 9)})

    def test_live_discovery_retries_for_product_pages_without_inventing_list_prices(self) -> None:
        from backend.workflow import ExtractionAgent, SearchAgent

        listing = {"title": "Office chairs under Rs 15000", "url": "https://shop.example/collections/office-chairs"}
        article = {"title": "Best office chairs 2026", "url": "https://review.example/blogs/best-chairs"}
        tracker = {"title": "Acme Ergo Chair price history", "url": "https://camelcamelcamel.com/product/B123"}
        wrong_item = {"title": "Ergonomic gaming mouse", "url": "https://shop.example/products/ergo-mouse"}
        product = {"title": "Acme Ergo Chair", "url": "https://shop.example/products/acme-ergo-chair", "snippet": "Price ₹9,000"}
        agent = SearchAgent()
        agent.client.api_key = "test"
        brief = {"category": "Office chair", "description": "An ergonomic office chair", "budget": 12000,
                 "arrive_by": "within 5 days", "location": "Bengaluru", "must_have": ["back support"]}
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}), patch.object(
            agent.client, "scrape_inline", return_value={
                "generatedJson": {"name": "Aurora teal ergonomic chair"}, "markdown": "Cookie settings and privacy choices"
            },
        ), patch.object(
            agent.client, "search", side_effect=[{"results": [listing, article, tracker, wrong_item]}, {"results": [product]}, {"results": []}],
        ) as search:
            sources, event, meta = agent.run(brief, "https://social.example/posts/aurora")

        self.assertEqual(search.call_count, 3)
        self.assertEqual(sources, [product])
        self.assertIn("back support", search.call_args_list[0].args[0])
        self.assertIn("Aurora teal ergonomic chair", search.call_args_list[0].args[0])
        self.assertNotIn("Cookie settings", search.call_args_list[0].args[0])
        self.assertEqual(event["status"], "complete")
        self.assertEqual(meta["mode"], "live")
        self.assertEqual(ExtractionAgent()._from_live(listing, 0)["price"], 0)
        self.assertEqual(ExtractionAgent().run([], {"mode": "live"})[0], [])

    def test_unstructured_direct_page_is_not_purchase_evidence(self) -> None:
        from backend.workflow import ResearchAgent

        agent = ResearchAgent()
        product = {"id": "search-only", "name": "Linen Overshirt", "url": "https://retailer.example/overshirt", "price": 900}
        with patch.object(agent.client, "scrape_inline", return_value={"markdown": "Welcome to our summer sale"}):
            enriched, completed = agent._one(product)

        self.assertFalse(completed)
        self.assertNotEqual(enriched.get("research_status"), "complete")

    def test_accessory_cannot_be_recommended_as_requested_product(self) -> None:
        from backend.workflow import RankingAgent, SearchAgent, _mission_decision

        brief = {"category": "Office chair", "description": "Find an office chair", "budget": 2000, "arrive_by_days": 5}
        cover = {"id": "cover", "name": "Acme Office Chair Cover", "url": "https://shop.example/products/chair-cover",
                 "source_kind": "live_web", "research_status": "complete", "price_verification": "matched",
                 "price": 1000, "shipping_cost": 0, "shipping_verified": True, "delivery_days": 2,
                 "stock": 10, "currency": "INR"}
        ranked, _ = RankingAgent().run([cover], brief)
        self.assertFalse(ranked[0]["category_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "no_safe_fit")

        agent = SearchAgent()
        agent.client.api_key = "test"
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}), patch.object(
            agent.client, "search", return_value={"results": [{"title": cover["name"], "url": cover["url"]}]}
        ):
            sources, _, _ = agent.run(brief, None)
        self.assertEqual(sources, [])
        generic_brief = {**brief, "category": "Shopping"}
        self.assertFalse(RankingAgent().run([cover.copy()], generic_brief)[0][0]["category_fit"])
        seat_cover = {**cover, "name": "Acme Office Chair Seat Cover"}
        self.assertFalse(RankingAgent().run([seat_cover], brief)[0][0]["category_fit"])

    def test_generic_description_keeps_the_requested_product_noun(self) -> None:
        from backend.workflow import SearchAgent, _requested_product_noun

        agent = SearchAgent()
        agent.client.api_key = "test"
        for description, noun in (("Find a laptop I can use daily", "laptop"),
                                  ("A sofa that fits my living room", "sofa")):
            brief = {"category": "Shopping", "description": description}
            self.assertEqual(_requested_product_noun(brief), noun)
            with self.subTest(noun=noun), patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}), patch.object(
                agent.client, "search", return_value={"results": [{"title": f"Acme {noun}", "url": f"https://shop.example/products/{noun}", "snippet": "Price ₹9,000"}]}
            ):
                sources, _, _ = agent.run(brief, None)
            self.assertEqual(len(sources), 1)

    def test_variant_sold_count_is_not_available_stock(self) -> None:
        from backend.workflow import RankingAgent, _mission_decision

        brief = {"category": "Shirt", "description": "Red shirt", "budget": 2000,
                 "arrive_by_days": 5, "color": "red", "size": "M"}
        shirt = {"id": "shirt", "name": "Acme Shirt", "url": "https://shop.example/products/shirt",
                 "source_kind": "live_web", "research_status": "complete", "price_verification": "direct",
                 "price": 900, "direct_page_price": 900, "shipping_cost": 0, "shipping_verified": True,
                 "delivery_days": 2, "stock": 10, "currency": "INR",
                 "variants": [{"color": "red", "size": "M", "available": True, "stock": "100 sold", "price": 900}]}
        ranked, _ = RankingAgent().run([shirt], brief)
        self.assertIsNone(ranked[0]["variant_fit"])
        self.assertEqual(_mission_decision(ranked, brief)["status"], "verify_before_buy")

    def test_unverified_review_metadata_does_not_become_a_reliability_score(self) -> None:
        from backend.workflow import AnalysisAgent, RankingAgent

        score, analysis = AnalysisAgent._review_signal({
            "source_kind": "live_web",
            "review_reliability": 0.99,
            "review_sources": [{"name": "Retailer reviews", "count": 400, "rating": 4.8}],
        })
        self.assertIsNone(score)
        self.assertIn("do not verify reviewer identity", analysis["detail"])

        brief = {"budget": 2000, "arrive_by_days": 5, "quantity": 1, "must_have": []}
        base = {
            "name": "Product",
            "price": 1000,
            "source_kind": "live_web",
            "research_status": "complete",
            "shipping_cost": 0,
            "delivery_days": 2,
            "currency": "INR",
            "seller": "Retailer",
        }
        ranked, _ = RankingAgent().run([
            {**base, "id": "high-signal", "seller_reliability": 0.99},
            {**base, "id": "low-signal", "seller_reliability": 0.01},
        ], brief)
        self.assertEqual(ranked[0]["match_score"], ranked[1]["match_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
