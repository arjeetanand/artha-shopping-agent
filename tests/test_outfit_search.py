"""The beach outfit must survive budget entry, clarification, and discovery."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.clients import AnakinClient
from backend.db import Database
from backend.workflow import BriefAgent, RankingAgent, SearchAgent, _decision_selection, _merge_refinement_intent, _mission_decision, _outfit_details, run_refinement, run_search


TEXT = "half pant cream / white and white shirt for beach"


class OutfitSearchTests(unittest.TestCase):
    def brief(self, budget="under2k"):
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "fixture"}):
            return BriefAgent().run({"text": TEXT, "mission": {"budget": budget, "pincode": "560001"}})[0]

    def test_budget_shorthand_and_separate_outfit_questions(self):
        for value in ["under2k", "2k", "₹2,000", "2000"]:
            with self.subTest(value=value):
                brief = self.brief(value)
                self.assertEqual(brief["budget"], 2000)
        self.assertEqual({item["key"] for item in brief["items"]}, {"shorts", "shirt"})
        self.assertEqual(next(item for item in brief["items"] if item["key"] == "shorts")["color_options"], ["cream", "white"])
        self.assertEqual(brief["items"][1]["color_options"], ["white"])
        self.assertEqual({q["key"] for q in brief["clarifications"]}, {"shorts_size", "shirt_size", "wearer", "budget_scope", "delivery"})

    def test_answers_finish_the_brief_without_losing_the_original_outfit(self):
        brief = _merge_refinement_intent(self.brief(), "shirt size M; shorts size 32; for men; budget for the whole outfit; within 5 days")
        self.assertEqual(brief["clarifications"], [])
        self.assertEqual(brief["items"][0]["size"], "32")
        self.assertEqual(brief["items"][1]["size"].lower(), "m")
        self.assertEqual(brief["budget_scope"], "outfit")
        self.assertEqual(brief["wearer"], "men")
        self.assertEqual(brief["budget"], 2000)
        self.assertEqual(brief["pincode"], "560001")

    def test_half_pant_phrase_keeps_the_bottom_and_shirt_as_separate_items(self):
        text = "white shirt and half cream or white pant for beach"
        brief = {"category": "shirt", "description": text, "raw_text": text}
        _outfit_details(brief, text)

        self.assertEqual({item["key"] for item in brief["items"]}, {"shorts", "shirt"})
        self.assertEqual(next(item for item in brief["items"] if item["key"] == "shorts")["color_options"], ["cream", "white"])

        agent = SearchAgent()
        agent.anakin.api_key = "test"
        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}), patch.object(
            agent.anakin, "search", side_effect=lambda query, num_results=10: {
                "results": [{
                    "title": "Men cream shorts" if "shorts" in query.lower() else "Men white shirt",
                    "url": f"https://store.in/products/{'shorts' if 'shorts' in query.lower() else 'shirt'}",
                }]
            },
        ):
            products, _, _ = agent.run(brief, None)
        self.assertEqual({product["request_item"] for product in products}, {"shorts", "shirt"})

    def test_discovery_searches_for_both_items_with_their_own_colors(self):
        brief = _merge_refinement_intent(self.brief(), "shirt size M; shorts size 32; for men; budget for the whole outfit; within 5 days")
        agent = SearchAgent()
        agent.anakin.api_key = "test"

        def search(query, num_results=10):
            key = "shorts" if "shorts" in query.lower() else "shirt"
            return {"results": [{"title": f"Beach {key}", "url": f"https://store.in/products/{key}"}]}

        with patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live"}), patch.object(agent.anakin, "search", side_effect=search) as searched:
            products, _, _ = agent.run(brief, None)
        self.assertEqual({p["request_item"] for p in products}, {"shorts", "shirt"})
        queries = [call.args[0].lower() for call in searched.call_args_list]
        self.assertTrue(any("cream" in q and "shorts" in q for q in queries))
        self.assertTrue(any("white" in q and "shirt" in q and "cream" not in q for q in queries))

    def test_whole_outfit_selection_obeys_the_combined_budget(self):
        brief = _merge_refinement_intent(self.brief(), "shirt size M; shorts size 32; for men; budget for the whole outfit; within 5 days")
        products = [
            {"id": "shorts", "request_item": "shorts", "price": 700, "eligible": True, "color_fit": True, "match_score": 80},
            {"id": "shirt-expensive", "request_item": "shirt", "price": 1500, "eligible": True, "color_fit": True, "match_score": 99},
            {"id": "shirt", "request_item": "shirt", "price": 1200, "eligible": True, "color_fit": True, "match_score": 80},
        ]
        decision = _mission_decision(products, brief)
        self.assertEqual({p["id"] for p in _decision_selection(products, decision)}, {"shorts", "shirt"})
        self.assertEqual(decision["total"], 1900)
        per_item = _mission_decision(products, {**brief, "budget_scope": "item"})
        self.assertEqual(per_item["total"], 2200)
        duplicate = [{**products[0], "url": "https://store.in/products/set"}, {**products[2], "url": "https://store.in/products/set"}]
        self.assertEqual(_mission_decision(duplicate, brief)["status"], "no_safe_fit")
        decision = _mission_decision(products[:1], brief)
        self.assertEqual(decision["status"], "no_safe_fit")
        self.assertEqual(_decision_selection(products[:1], decision), [])

    def test_clarification_resumes_into_a_complete_two_piece_shortlist(self):
        with tempfile.TemporaryDirectory(prefix="artha-outfit-", dir="/private/tmp") as directory:
            database = Database(Path(directory) / "test.db")
            with patch("backend.workflow.db", database), patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "fixture"}):
                waiting = run_search({"text": TEXT, "mission": {"budget": "2k", "pincode": "560001"}})
            self.assertEqual(waiting["status"], "needs_clarification")
            self.assertEqual(waiting["products"], [])
            products = {
                "shorts": {"name": "Men Cream Beach Shorts", "price": 700, "color": "cream", "size": "32"},
                "shirt": {"name": "Men White Beach Shirt", "price": 1200, "color": "white", "size": "M"},
            }

            def search(query, num_results=10):
                key = "shorts" if "shorts" in query.lower() else "shirt"
                return {"results": [{"title": products[key]["name"], "url": f"https://store.in/products/{key}"}]}

            def scrape(url, **kwargs):
                p = products[url.rsplit("/", 1)[-1]]
                return {"generatedJson": {"name": p["name"], "pageType": "productDetail", "price": p["price"], "currency": "INR", "shipping_cost": 0,
                        "stock": 5, "delivery_days": 3, "colors": [p["color"]], "sizes": [p["size"]],
                        "variants": [{"color": p["color"], "size": p["size"], "price": p["price"], "stock": 5, "available": True}]}}

            with patch("backend.workflow.db", database), patch.dict(os.environ, {"SHOPPINGHELP_SEARCH_MODE": "live", "ANAKIN_API_KEY": "test"}), \
                    patch.object(AnakinClient, "search", side_effect=search), patch.object(AnakinClient, "scrape_inline", side_effect=scrape):
                result = run_refinement({"search_id": waiting["search_id"], "text": "shirt size M; shorts size 32; for men; budget for the whole outfit; within 5 days", "mission": waiting["intent"]["mission"]})
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(result["selected_product_ids"]), 2)
            self.assertEqual(result["summary"]["total"], 1900)
            self.assertEqual(result["intent"]["clarifications"], [])

    def test_color_alternatives_apply_only_to_their_outfit_piece(self):
        brief = _merge_refinement_intent(self.brief(), "shirt size M; shorts size 32; for men; budget per item; within 5 days")
        products = [
            {"id": "shorts", "name": "White Shorts", "request_item": "shorts", "price": 700, "colors": ["white"], "sizes": ["32"]},
            {"id": "shirt", "name": "Cream Shirt", "request_item": "shirt", "price": 700, "colors": ["cream"], "sizes": ["M"]},
        ]
        ranked, _ = RankingAgent().run(products, brief)
        self.assertTrue(ranked[0]["color_fit"])
        self.assertFalse(ranked[1]["color_fit"])
        wrong_wearer = {"id": "wrong", "name": "Women White Shirt", "request_item": "shirt", "price": 700, "colors": ["white"], "sizes": ["M"]}
        self.assertFalse(RankingAgent().run([wrong_wearer], brief)[0][0]["eligible"])

    def test_requested_color_must_be_supported_by_the_listing_before_recommendation(self):
        brief = {"category": "Shirt", "description": "white shirt", "budget": 2000, "color": "white", "must_have": []}
        products = [
            {"id": "white", "name": "White Linen Shirt", "price": 1200},
            {"id": "blue", "name": "Blue Linen Shirt", "price": 900},
            {"id": "unknown", "name": "Linen Shirt", "price": 800},
        ]
        ranked, _ = RankingAgent().run(products, brief)
        by_id = {product["id"]: product for product in ranked}

        self.assertIs(by_id["white"]["color_fit"], True)
        self.assertIs(by_id["blue"]["color_fit"], False)
        self.assertIsNone(by_id["unknown"]["color_fit"])
        self.assertTrue(by_id["white"]["eligible"])
        self.assertFalse(by_id["blue"]["eligible"])
        self.assertFalse(by_id["unknown"]["eligible"])

        stale_unknown = {**by_id["unknown"], "eligible": True}
        decision = _mission_decision([stale_unknown], brief)
        self.assertEqual(decision["status"], "no_safe_fit")
        self.assertIn("colour", " ".join(decision["blocking_risks"]).lower())
        self.assertIn("colour variant", decision["mission_change"].lower())
        decision = _mission_decision([by_id["blue"], by_id["white"]], brief)
        self.assertEqual(decision["recommended_product_id"], "white")

    def test_budget_accepts_decimal_shorthand_but_rejects_invalid_amounts(self):
        self.assertEqual(self.brief("2.5k")["budget"], 2500)
        for value in ["-2000", "banana", "2000-3000", True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.brief(value)


if __name__ == "__main__":
    unittest.main()
