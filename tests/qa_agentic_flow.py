"""Focused QA contracts for the next agentic shopping-flow increment.

These tests deliberately cover behavior that is not represented by the existing
offline contracts. A red test is a concrete implementation gap, not a reason to
weaken the contract to match the current behavior.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AgenticFlowContracts(unittest.TestCase):
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

    def test_written_delivery_duration_is_parsed_without_becoming_location(self) -> None:
        """Natural-language durations must not fall through to the location parser."""
        from backend.workflow import BriefAgent

        brief, _event = BriefAgent().run(
            {"text": "A cool dress under ₹1,000 delivered in three days"}
        )

        self.assertEqual(brief.get("arrive_by_days"), 3)
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

        with patch.object(db, "save_search"):
            result = run_refinement(
                {
                    "text": "Show me red options in size M",
                    "intent": previous_intent,
                    "products": [product],
                    "source": {"mode": "sandbox"},
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
        with patch.object(agent.anakin, "scrape_inline", return_value={}):
            enriched, completed = agent._one(product)

        self.assertFalse(completed)
        self.assertNotEqual(enriched.get("research_status"), "complete")


if __name__ == "__main__":
    unittest.main(verbosity=2)
