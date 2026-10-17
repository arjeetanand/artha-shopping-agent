"""Observed price evidence must never be confused with sourced claims or fixtures."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import Database  # noqa: E402
from backend.price_history import enrich_price_evidence  # noqa: E402
from backend.clients import AnakinClient  # noqa: E402
from backend.workflow import RankingAgent, ResearchAgent, _mission_decision, _targeted_cross_store_offers  # noqa: E402


class PriceHistoryContracts(unittest.TestCase):
    @staticmethod
    def _explicit_inr(products: list[dict]) -> list[dict]:
        for product in products:
            product.setdefault("currency", "INR")
        return products

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database(Path(self.directory.name) / "prices.sqlite3")

    def test_direct_product_jsonld_gtin_matches_different_titles(self) -> None:
        agent = ResearchAgent()
        products = []
        for index, title in enumerate(("Acme Model X Chair", "Acme Ergonomic Chair Model X", "Acme Model X Chair Sale")):
            product = {"id": str(index), "brand": "Acme", "name": title, "price": 100 - index * 10,
                       "url": f"https://store{index}.example/chair", "source_kind": "live_web"}
            jsonld = f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product","name":"{title}","gtin13":"5901234123457"}}</script>'
            scrape = {"generatedJson": {"pageType": "productDetail", "name": title, "price": product["price"], "currency": "INR", "gtin": "5901234123457"},
                      "html": jsonld if index < 2 else "<html>No Product JSON-LD</html>"}
            with patch.object(agent.anakin, "scrape_inline", return_value=scrape):
                checked, ok = agent._one(product)
            self.assertTrue(ok)
            products.append(checked)

        enriched = enrich_price_evidence(self.db, products, source_mode="live")
        self.assertEqual([product["same_product_match"] for product in enriched], ["gtin", "gtin", "source_url_only"])
        self.assertEqual([offer["price"] for offer in enriched[0]["current_offers"]], [90, 100])
        self.assertEqual(enriched[0]["lowest_current_offer"]["source_url"], "https://store1.example/chair")
        self.assertEqual([offer["price"] for offer in enriched[2]["current_offers"]], [80])
        bad_check_digit = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Acme Chair","gtin13":"5901234123458"}</script>'
        self.assertIsNone(agent._page_gtin(bad_check_digit, "Acme Chair"))

    def test_private_retailer_url_is_not_scraped(self) -> None:
        agent = ResearchAgent()
        with patch.object(agent.anakin, "scrape_inline") as scrape:
            checked, ok = agent._one({"name": "Chair", "url": "http://127.0.0.1/private"})
        self.assertFalse(ok)
        self.assertEqual(checked["research_status"], "waiting")
        scrape.assert_not_called()
        _products, _event, source = agent.run([{"name": "Chair", "url": "https://["}], {"mode": "live"})
        self.assertEqual(source["research"]["attempted"], 0)

    def test_exact_match_current_offers_and_recorded_history(self) -> None:
        products = [
            {"id": "a", "brand": "Acme", "name": "Widget X1", "color": "Black", "size": "M", "price": 120, "seller": "Store A", "url": "https://a.example/x1", "source_kind": "live_web", "research_status": "complete", "price_verification": "matched"},
            {"id": "b", "brand": "Acme", "name": "Widget X1", "color": "Black", "size": "M", "price": 100, "seller": "Store B", "url": "https://b.example/x1", "source_kind": "live_web", "research_status": "complete", "price_verification": "matched"},
            {"id": "c", "brand": "Acme", "name": "Widget X1", "color": "Blue", "size": "M", "price": 80, "seller": "Store C", "url": "https://c.example/x1", "source_kind": "live_web", "research_status": "complete", "price_verification": "direct"},
        ]
        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live", observed_at="2026-09-01T10:00:00+00:00")
        self.assertEqual([offer["price"] for offer in enriched[0]["current_offers"]], [100, 120])
        self.assertEqual(enriched[0]["lowest_current_offer"]["source_url"], "https://b.example/x1")
        self.assertEqual(enriched[2]["current_offers"][0]["price"], 80)
        self.assertEqual(enriched[0]["price_history"]["status"], "first_observation")

        next_search = [dict(products[0], price=90)]
        enriched = enrich_price_evidence(self.db, next_search, source_mode="live", observed_at="2026-09-03T10:00:00+00:00")
        self.assertEqual([offer["price"] for offer in enriched[0]["current_offers"]], [90])
        history = enriched[0]["price_history"]
        self.assertEqual(history["status"], "observed")
        self.assertEqual(history["observation_count"], 3)
        self.assertEqual(history["observed_low"], 90)
        self.assertEqual(history["first_observed_at"], "2026-09-01T10:00:00+00:00")
        self.assertEqual(history["last_observed_at"], "2026-09-03T10:00:00+00:00")
        self.assertEqual(len(Database(self.db.path).price_observations(enriched[0]["product_key"])), 3)

    def test_unbranded_products_do_not_merge_across_sites(self) -> None:
        products = [
            {"id": "a", "name": "Cotton shirt", "price": 100, "url": "https://a.example/shirt", "research_status": "complete", "price_verification": "matched"},
            {"id": "b", "name": "Cotton shirt", "price": 80, "url": "https://b.example/shirt", "research_status": "complete", "price_verification": "direct"},
        ]
        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live")
        self.assertEqual(enriched[0]["same_product_match"], "source_url_only")
        self.assertEqual(len(enriched[0]["current_offers"]), 1)
        self.assertEqual(enriched[0]["lowest_current_offer"]["price"], 100)

    def test_color_lists_do_not_merge_different_variants_across_sites(self) -> None:
        products = [
            {"id": "blue", "brand": "Acme", "name": "Widget X1", "colors": ["Blue"], "price": 100, "url": "https://blue.example/x1", "research_status": "complete", "price_verification": "matched"},
            {"id": "red", "brand": "Acme", "name": "Widget X1", "colors": ["Red"], "price": 80, "url": "https://red.example/x1", "research_status": "complete", "price_verification": "matched"},
        ]

        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live")

        self.assertEqual([offer["price"] for offer in enriched[0]["current_offers"]], [100])
        self.assertEqual([offer["price"] for offer in enriched[1]["current_offers"]], [80])
        self.assertNotEqual(enriched[0]["product_key"], enriched[1]["product_key"])

    def test_unknown_variant_does_not_merge_generic_titles_across_sites(self) -> None:
        products = [
            {"id": "small", "brand": "Acme", "name": "Everyday shirt", "price": 100, "url": "https://a.example/small", "research_status": "complete", "price_verification": "matched"},
            {"id": "large", "brand": "Acme", "name": "Everyday shirt", "price": 80, "url": "https://b.example/large", "research_status": "complete", "price_verification": "matched"},
        ]
        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live")
        self.assertEqual([item["same_product_match"] for item in enriched], ["source_url_only", "source_url_only"])
        self.assertEqual([item["lowest_current_offer"]["price"] for item in enriched], [100, 80])

    def test_one_retailer_url_does_not_merge_explicit_variants(self) -> None:
        products = [
            {"id": "small", "name": "Everyday shirt", "color": "Blue", "size": "S", "price": 100, "url": "https://a.example/shirt", "research_status": "complete", "price_verification": "matched"},
            {"id": "large", "name": "Everyday shirt", "color": "Blue", "size": "L", "price": 80, "url": "https://a.example/shirt", "research_status": "complete", "price_verification": "matched"},
        ]
        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live")
        self.assertNotEqual(enriched[0]["product_key"], enriched[1]["product_key"])
        self.assertEqual([item["lowest_current_offer"]["price"] for item in enriched], [100, 80])

    def test_tracking_links_share_history_but_variant_parameters_do_not(self) -> None:
        common = {"id": "chair", "name": "Acme Chair", "currency": "INR", "research_status": "complete",
                  "price_verification": "direct", "source_kind": "live_web"}
        first = {**common, "price": 100,
                 "url": "https://shop.example/products/chair?variant=blue&utm_source=search#details"}
        second = {**common, "price": 80,
                  "url": "https://shop.example/products/chair?variant=blue&gclid=abc#reviews"}
        other_variant = {**common, "price": 70,
                         "url": "https://shop.example/products/chair?variant=red&utm_campaign=sale"}

        first = enrich_price_evidence(self.db, [first], source_mode="live", observed_at="2026-09-01T10:00:00+00:00")[0]
        second = enrich_price_evidence(self.db, [second], source_mode="live", observed_at="2026-09-03T10:00:00+00:00")[0]
        other_variant = enrich_price_evidence(self.db, [other_variant], source_mode="live", observed_at="2026-09-03T10:00:00+00:00")[0]

        self.assertEqual(first["product_key"], second["product_key"])
        self.assertNotEqual(second["product_key"], other_variant["product_key"])
        self.assertEqual(second["price_history"]["observed_low"], 80)
        self.assertEqual(second["price_history"]["observation_count"], 2)
        self.assertEqual(other_variant["price_history"]["observation_count"], 1)

    def test_untrusted_history_and_invalid_offers_are_not_persisted(self) -> None:
        products = [
            {"id": "a", "brand": "Acme", "name": "Widget", "price": 100, "url": "https://a.example/widget", "price_history": {"low_90d": 1}, "research_status": "complete", "price_verification": "matched"},
            {"id": "b", "brand": "Acme", "name": "Widget", "price": 1, "url": "https://b.example/widget", "research_status": "complete", "price_verification": "mismatch"},
            {"id": "c", "brand": "Acme", "name": "Widget Y", "price": 1, "url": "javascript:alert(1)", "research_status": "complete", "price_verification": "direct"},
            {"id": "d", "brand": "Acme", "name": "Widget Y", "price": 1, "url": "https://[", "research_status": "complete", "price_verification": "direct"},
            {"id": "e", "brand": "Acme", "name": "Widget Z", "price": 1, "url": "https://e.example/widget", "research_status": "waiting"},
            {"id": "f", "brand": "Acme", "name": "Widget Q", "price": 1, "url": "https://f.example/widget", "research_status": "complete", "price_verification": "direct", "currency": "USD"},
        ]
        enriched = enrich_price_evidence(self.db, self._explicit_inr(products), source_mode="live")
        self.assertEqual(enriched[0]["price_history"]["status"], "first_observation")
        self.assertNotIn("low_90d", enriched[0]["price_history"])
        self.assertEqual(len(enriched[0]["current_offers"]), 1)
        self.assertEqual(enriched[1]["price_history"]["status"], "unknown")
        self.assertEqual(enriched[2]["price_history"]["status"], "unknown")
        self.assertEqual(enriched[3]["price_history"]["status"], "unknown")
        self.assertEqual(enriched[4]["current_offers"], [])
        self.assertEqual(enriched[5]["current_offers"], [])

        fixture = enrich_price_evidence(self.db, [{"id": "f", "name": "Demo", "price": 50, "url": "https://example.com/demo", "price_history": {"low_90d": 40, "trend_label": "Near its 90-day low"}}], source_mode="sandbox")
        self.assertEqual(fixture[0]["price_history"]["status"], "fixture")
        self.assertIn("Demo", fixture[0]["price_history"]["trend_label"])
        self.assertEqual(fixture[0]["current_offers"], [])
        self.assertEqual(self.db.price_observations(enriched[0]["product_key"])[0]["price"], 100)

    def test_direct_page_price_is_observed_even_when_search_price_was_stale(self) -> None:
        product = {"id": "chair", "name": "Office Chair", "price": 1500, "direct_page_price": 1500,
                   "url": "https://shop.example/chair", "source_kind": "live_web",
                   "research_status": "complete", "price_verification": "mismatch"}
        enriched = enrich_price_evidence(self.db, self._explicit_inr([product]), source_mode="live")
        self.assertEqual(enriched[0]["current_offers"][0]["price"], 1500)
        self.assertEqual(enriched[0]["price_history"]["status"], "first_observation")

    def test_checked_selected_variant_price_enters_history_after_base_price_changed(self) -> None:
        product = {"id": "shirt", "name": "Acme Shirt", "url": "https://shop.example/products/shirt",
                   "price": 800, "source_kind": "live_web"}
        brief = {"category": "Shirt", "budget": 3000, "arrive_by_days": 5,
                 "color": "red", "size": "M", "must_have": []}
        agent = ResearchAgent()
        with patch.object(agent.anakin, "scrape_inline", return_value={"generatedJson": {
            "pageType": "productDetail", "name": "Acme Shirt", "price": 900, "currency": "INR",
            "stock": 2, "shipping_cost": 0, "delivery_days": 2,
            "variants": [{"color": "red", "size": "M", "available": True, "stock": 2, "price": 2000}],
        }}):
            checked, ok = agent._one(product)
        self.assertTrue(ok)
        ranked, _ = RankingAgent().run([checked], brief)
        enriched = enrich_price_evidence(self.db, ranked, source_mode="live")
        self.assertEqual(enriched[0]["price_verification"], "mismatch")
        self.assertEqual(enriched[0]["direct_page_price"], 2000)
        self.assertEqual(enriched[0]["current_offers"][0]["price"], 2000)
        self.assertEqual(enriched[0]["price_history"]["observation_count"], 1)
        self.assertEqual((enriched[0]["color"], enriched[0]["size"]), ("red", "M"))

    def test_targeted_lookup_checks_unique_stores_and_ranks_verified_lower_offer(self) -> None:
        original = {"id": "original", "name": "Acme Model X Chair", "brand": "Acme", "category": "Office chair",
                    "price": 4000, "currency": "INR", "shipping_cost": 0, "shipping_verified": True,
                    "stock": 5, "delivery_days": 2, "url": "https://a.example/products/chair",
                    "source_kind": "live_web", "research_status": "complete", "price_verification": "matched",
                    "gtin": "5901234123457", "gtin_source": "direct_product_jsonld"}
        brief = {"budget": 5000, "arrive_by_days": 5, "quantity": 1, "must_have": [], "nice_to_have": []}
        results = [
            {"title": "Acme Model X Chair", "url": "https://b.example/products/chair",
             "generatedJson": {"pageType": "productDetail", "name": "Acme Model X Chair", "price": 3500, "currency": "INR"}},
            {"title": "Acme Model X Chair", "url": "https://b.example/products/chair-sale",
             "generatedJson": {"pageType": "productDetail", "name": "Acme Model X Chair", "price": 3400, "currency": "INR"}},
            {"title": "Acme Model X Chair", "url": "https://c.example/products/chair",
             "generatedJson": {"pageType": "productDetail", "name": "Acme Model X Chair", "price": 1000, "currency": "INR"}},
        ]
        scraped = {}
        for url, price, gtin in ((results[0]["url"], 3500, "5901234123457"),
                                 (results[2]["url"], 1000, "4006381333931")):
            scraped[url] = {
                "generatedJson": {"pageType": "productDetail", "name": "Acme Model X Chair", "price": price,
                                  "currency": "INR", "shipping_cost": 0, "stock": 5, "delivery_days": 2},
                "html": f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product","name":"Acme Model X Chair","gtin13":"{gtin}"}}</script>',
            }
        source = {"mode": "live"}
        with patch.object(AnakinClient, "search", return_value={"results": results}) as search, \
             patch.object(AnakinClient, "scrape_inline", side_effect=lambda url, **kwargs: scraped[url]) as scrape:
            other_offers = _targeted_cross_store_offers([original], brief, source)
        search.assert_called_once()
        self.assertIn("5901234123457", search.call_args.args[0])
        self.assertEqual(scrape.call_count, 2)
        self.assertEqual(source["cross_store"]["attempted"], 2)
        self.assertEqual(source["cross_store"]["matched"], 1)
        self.assertEqual(len(other_offers), 1)
        enriched = enrich_price_evidence(self.db, [original] + other_offers, source_mode="live")
        self.assertEqual(len(enriched), 2)
        self.assertEqual([offer["price"] for offer in enriched[0]["current_offers"]], [3500, 4000])
        self.assertEqual(enriched[0]["lowest_current_offer"]["source_url"], results[0]["url"])
        self.assertEqual(enriched[0]["price_history"]["observation_count"], 2)
        ranked, _ = RankingAgent().run(enriched, brief)
        self.assertEqual(_mission_decision(ranked, brief)["recommended_product_id"], other_offers[0]["id"])
        self.assertEqual(len(self.db.price_observations(original["product_key"])), 2)

        other_offers[0]["shipping_cost"] = 1000
        other_offers[0]["total_price"] = 4500
        ranked, _ = RankingAgent().run(enriched, brief)
        self.assertEqual(_mission_decision(ranked, brief)["recommended_product_id"], original["id"])
        self.assertEqual(original["lowest_current_offer"]["price"], 3500)

        generic = {**original, "name": "Chair", "gtin": None, "gtin_source": None}
        with patch.object(AnakinClient, "search") as search:
            self.assertEqual(_targeted_cross_store_offers([generic], brief, {"mode": "live"}), [])
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
