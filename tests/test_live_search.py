"""Live search contracts with the external provider replaced by fixed responses."""

import json
import os
import unittest
from unittest.mock import patch

from backend.clients import AnakinClient
from backend.workflow import ExtractionAgent, ResearchAgent, SearchAgent, _mission_decision, run_search


class LiveSearchTests(unittest.TestCase):
    def setUp(self):
        mode = patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_PROVIDER": "anakin", "SHOPPINGHELP_SEARCH_MODE": "live", "ANAKIN_API_KEY": "test"})
        mode.start()
        self.addCleanup(mode.stop)

    def test_office_chair_search_keeps_indian_product_pages(self):
        agent = SearchAgent()
        results = [
            {"title": "Wakefit Gravita Ergonomic Office Chair", "url": "https://www.flipkart.com/wakefit-chair/p/itm123"},
            {"title": "Realspace Ergonomic Office Chair", "url": "https://www.officedepot.com/a/products/123/realspace"},
            {"title": "Office Chair Guide", "url": "https://example.in/blog/office-chair-guide"},
            {"title": "India Brand Office Chair", "url": "https://chairbrand.com/products/chair", "snippet": "Buy this chair for ₹8,999"},
        ]
        with patch.object(agent.client, "search", return_value={"results": results}) as search:
            products, _, _ = agent.run({"category": "Office chair", "description": "ergonomic office chair", "budget": 12000}, None)

        self.assertEqual([item["url"] for item in products], [results[0]["url"], results[3]["url"]])
        self.assertFalse(any("myntra" in call.args[0] for call in search.call_args_list))

    def test_shirt_search_excludes_t_shirts(self):
        agent = SearchAgent()
        results = [
            {"title": "Men Solid White Shirt", "url": "https://www.flipkart.com/products/shirt"},
            {"title": "Men Crew Neck White T-Shirt", "url": "https://www.flipkart.com/products/tshirt"},
        ]
        with patch.object(agent.client, "search", return_value={"results": results}):
            products, _, _ = agent.run({"category": "Shirt", "description": "white shirt"}, None)
        self.assertEqual([product["url"] for product in products], [results[0]["url"]])
        with patch.object(agent.client, "search", return_value={"results": results}):
            products, _, _ = agent.run({"category": "T-shirt", "description": "white t-shirt"}, None)
        self.assertEqual([product["url"] for product in products], [results[1]["url"]])

    def test_long_search_title_can_match_the_exact_direct_product(self):
        raw = {
            "title": "Wakefit Gravita Ergonomic Chair for Work | Single Lock and Recline | Nylon Base | Mesh Office Adjustable Arm Chair Price in India - Buy Wakefit Gravita Ergonomic Chair for Work",
            "url": "https://www.flipkart.com/wakefit-gravita/p/itm123",
        }
        product = ExtractionAgent()._from_live(raw, 0)
        agent = ResearchAgent()
        scraped = {"generatedJson": {"data": {
            "name": "Wakefit Gravita Ergonomic Chair for Work | Single Lock and Recline | Nylon Base | Mesh Office Adjustable Arm Chair",
            "pageType": "productDetail", "price": "5499", "currency": "₹",
        }}}
        with patch.object(agent.client, "scrape_inline", return_value=scraped):
            checked, ok = agent._one(product)

        self.assertTrue(ok)
        self.assertEqual(checked["price"], 5499)
        self.assertEqual(checked["currency"], "INR")

    def test_search_image_is_normalized_and_invalid_sentinels_are_dropped(self):
        product = ExtractionAgent()._from_live({
            "title": "Acme Shirt", "url": "https://store.in/products/shirt",
            "data": {"name": "Acme Shirt", "image": "None"},
            "image": "https://cdn.store.in/images/acme-shirt.jpg",
        }, 0)
        self.assertEqual(product["image"], "https://cdn.store.in/images/acme-shirt.jpg")
        missing = ExtractionAgent()._from_live({
            "title": "Acme Shirt", "url": "https://store.in/products/shirt",
            "data": {"name": "Acme Shirt", "image": "None"},
        }, 0)
        self.assertEqual(missing["image"], "")

    def test_direct_product_jsonld_supplies_its_exact_image(self):
        url = "https://store.in/products/acme-shirt"
        product = {"id": "shirt", "name": "Acme Shirt", "url": url, "price": 1200, "image": "None"}
        schema = {
            "@context": "https://schema.org", "@type": "Product", "name": "Acme Shirt",
            "image": ["/images/acme-shirt-main.jpg"],
        }
        scraped = {"finalUrl": url, "generatedJson": {"name": "Acme Shirt", "pageType": "productDetail",
                   "price": 1200, "currency": "INR"},
                   "html": '<script type="application/ld+json">' + json.dumps(schema) + '</script>'}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value=scraped):
            checked, ok = agent._one(product)
        self.assertTrue(ok)
        self.assertEqual(checked["image"], "https://store.in/images/acme-shirt-main.jpg")

    def test_no_recommendation_when_every_price_is_unknown(self):
        decision = _mission_decision([{"id": "chair", "name": "Chair", "eligible": True, "price": 0}], {"budget": 12000})
        self.assertIsNone(decision["recommended_product_id"])
        self.assertEqual(decision["status"], "no_safe_fit")

    def test_an_unknown_price_does_not_displace_a_priced_option(self):
        decision = _mission_decision([
            {"id": "unknown", "eligible": True, "price": 0},
            {"id": "priced", "eligible": True, "price": 7490},
        ], {"budget": 12000})
        self.assertEqual(decision["recommended_product_id"], "priced")

    def test_direct_product_schema_survives_a_provider_recommendations_list(self):
        product = {"id": "chair", "name": "Buy Green Soul New York Office Chair Online", "url": "https://www.flipkart.com/green-soul/p/itm123", "price": 0}
        schema = {
            "@context": "https://schema.org", "@type": "Product", "name": "Green Soul New York Office Chair",
            "brand": {"name": "Green Soul"}, "offers": {"@type": "Offer", "price": 7490, "priceCurrency": "INR", "availability": "https://schema.org/OutOfStock"},
        }
        raw = {"finalUrl": product["url"], "generatedJson": {"data": {"products": [{"name": "Unrelated chair", "price": 100}]}},
               "html": '<script type="application/ld+json">' + json.dumps(schema) + '</script>'}
        agent = ResearchAgent()
        with patch.object(agent.client, "scrape_inline", return_value=raw):
            checked, ok = agent._one(product)
        self.assertTrue(ok)
        self.assertEqual(checked["price"], 7490)
        self.assertEqual(checked["currency"], "INR")
        self.assertEqual(checked["stock"], 0)
        for final_url in ["https://www.flipkart.com/search?q=chair", "https://www.flipkart.com/other/p/itm999"]:
            with self.subTest(final_url=final_url), patch.object(agent.client, "scrape_inline", return_value={**raw, "finalUrl": final_url}):
                _, ok = agent._one(product)
            self.assertFalse(ok)

    def test_scraper_stops_polling_when_the_total_time_budget_is_used(self):
        with patch("backend.clients.time.monotonic", side_effect=[0, 46]), \
                patch("backend.clients._request_json", return_value={"status": "processing", "id": "job-slow"}), \
                patch("backend.clients.time.sleep") as sleep:
            with self.assertRaises(TimeoutError):
                AnakinClient().scrape_inline("https://www.flipkart.com/chair/p/itm123", max_wait_seconds=45)
        sleep.assert_not_called()

    def test_empty_search_does_not_invent_a_delivery_date(self):
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "fixture"}), \
                patch.object(SearchAgent, "run", return_value=([], {"agent": "Search agent", "status": "waiting"}, {"mode": "live"})), \
                patch("backend.workflow.db.save_search"):
            result = run_search({"text": "Office chair under ₹12,000 delivered to Bangalore within 5 days"})
        self.assertEqual(result["selected_product_ids"], [])
        self.assertEqual(result["summary"]["delivery_label"], "Confirm delivery at retailer")


if __name__ == "__main__":
    unittest.main()
