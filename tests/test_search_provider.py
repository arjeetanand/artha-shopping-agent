"""Offline contracts for free-tier discovery and local product extraction."""

import io
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from backend.clients import TavilyClient, get_search_client
from backend.workflow import ExtractionAgent, ResearchAgent, SearchAgent


class SearchProviderTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_PROVIDER": "tavily", "SHOPPINGHELP_SEARCH_MODE": "live", "TAVILY_API_KEY": "test-secret"})
        env.start()
        self.addCleanup(env.stop)
        validation = patch("backend.social._public_reference_url", side_effect=lambda url: (url, url))
        validation.start()
        self.addCleanup(validation.stop)

    def test_auto_prefers_free_tier_and_explicit_anakin_still_works(self):
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_PROVIDER": "auto"}):
            self.assertEqual(get_search_client().name, "tavily")
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_PROVIDER": "anakin"}):
            self.assertEqual(get_search_client().name, "anakin")

    def test_search_uses_basic_tier_and_normalizes_snippets(self):
        with patch("backend.clients._request_json", return_value={"results": [{"url": "https://store.in/products/chair", "title": "Office Chair", "content": "Price ₹999"}]}) as request, patch("backend.clients.record_usage"):
            response = TavilyClient().search("chair", 10)
        self.assertEqual(response["results"][0]["snippet"], "Price ₹999")
        args = request.call_args.kwargs
        self.assertEqual(args["payload"]["search_depth"], "basic")
        self.assertFalse(args["payload"]["auto_parameters"])
        self.assertEqual(args["headers"], {"Authorization": "Bearer test-secret"})

    def test_local_jsonld_reaches_product_research_without_api_credits(self):
        import json
        url = "https://store.in/products/chair"
        schema = {"@context": "https://schema.org", "@type": "Product", "name": "Office Chair", "offers": {"@type": "Offer", "price": "999", "priceCurrency": "INR"}}
        page = {"success": True, "title": "Office Chair", "finalUrl": url, "html": '<script type="application/ld+json">' + json.dumps(schema) + '</script>'}
        product = ExtractionAgent()._from_live({"url": url, "title": "Office Chair"}, 0)
        with patch("backend.social.capture_social_page", return_value=page), patch("backend.clients._request_json") as api:
            enriched, ok = ResearchAgent()._one(product)
        api.assert_not_called()
        self.assertTrue(ok)
        self.assertEqual(enriched["price"], 999)
        self.assertEqual(enriched["currency"], "INR")

    def test_retailer_queries_use_tavily_domain_filters(self):
        with patch("backend.clients._request_json", return_value={"results": []}) as request, patch("backend.clients.record_usage"):
            TavilyClient().search("office chair site:pepperfry.com OR site:ikea.com/in")
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["include_domains"], ["pepperfry.com", "ikea.com"])
        self.assertEqual(payload["query"], "office chair")

    def test_model_category_identifiers_are_human_readable_search_terms(self):
        agent = SearchAgent()
        with patch.object(agent.client, "search", return_value={"results": []}) as search:
            agent.run({"category": "office_chair", "description": "office chair", "budget": 12000}, None)
        self.assertTrue(all("office_chair" not in call.args[0] for call in search.call_args_list))

    def test_text_extract_is_reference_context_not_verified_price(self):
        response = {"results": [{"url": "https://store.in/products/chair", "raw_content": "Office Chair ₹999"}]}
        with patch("backend.social.capture_social_page", return_value={"success": False}), patch("backend.clients._request_json", return_value=response), patch("backend.clients.record_usage"):
            scraped = TavilyClient().scrape_inline("https://store.in/products/chair")
        self.assertIn("Office Chair", scraped["markdown"])
        self.assertNotIn("generatedJson", scraped)

    def test_quota_failure_is_actionable_and_not_retried_three_times(self):
        error = HTTPError("https://api.tavily.com/search", 432, "quota", {}, io.BytesIO(b"test-secret"))
        agent = SearchAgent()
        with patch.object(agent.client, "search", side_effect=error) as search:
            with self.assertRaisesRegex(RuntimeError, "Tavily.*credits") as caught:
                agent.run({"category": "Office chair", "description": "office chair"}, None)
        self.assertEqual(search.call_count, 1)
        self.assertNotIn("test-secret", str(caught.exception))

    def test_extract_200_with_all_urls_failed_is_an_error(self):
        with patch("backend.social.capture_social_page", return_value={"success": False}), patch("backend.clients._request_json", return_value={"results": [], "failed_results": [{"error": "blocked"}]}):
            with self.assertRaisesRegex(RuntimeError, "could not extract"):
                TavilyClient().scrape_inline("https://store.in/products/chair")


class TavilySafetyTests(unittest.TestCase):
    def test_private_targets_never_reach_browser_or_external_extract(self):
        with patch("backend.social.capture_social_page") as local, patch("backend.clients._request_json") as api:
            with self.assertRaises(ValueError):
                TavilyClient().scrape_inline("http://127.0.0.1/private")
        local.assert_not_called()
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
