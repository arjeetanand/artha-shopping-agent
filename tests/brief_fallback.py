"""Offline contract for keeping search usable when an LLM returns bad JSON."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with patch.dict(os.environ, {"APP_ENV": "development", "SHOPPINGHELP_SEARCH_MODE": "live"}, clear=False):
        from backend.workflow import BriefAgent

        agent = BriefAgent()
        with patch.object(agent.model, "extract_brief", return_value=(None, "ollama")), patch.object(
            agent.model,
            "status",
            return_value={"configured": True, "provider": "ollama"},
        ):
            brief, event = agent.run(
                {"text": "I need an office chair under ₹12,000 delivered to Bangalore within 5 days"}
            )

    assert brief["category"] == "Office chair"
    assert brief["budget"] == 12000
    assert brief["location"] == "Bengaluru"
    assert "local rules fallback" in brief["extraction_source"]
    assert event["status"] == "complete"
    assert "fallback" in event["detail"]
    print("brief_fallback_ok")


if __name__ == "__main__":
    main()
