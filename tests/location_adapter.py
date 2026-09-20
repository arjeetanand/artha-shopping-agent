"""Offline contract for permissioned Google Maps location enrichment."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.location import LocationAgent  # noqa: E402


class FakeResponse:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def fake_urlopen(request, timeout=8):
    del timeout
    if "places.googleapis.com" in request.full_url:
        return FakeResponse(
            {
                "places": [
                    {
                        "displayName": {"text": "Example Furniture Hub"},
                        "formattedAddress": "12 MG Road, Bengaluru",
                        "rating": 4.4,
                        "userRatingCount": 321,
                        "googleMapsUri": "https://maps.google.com/?cid=example",
                    }
                ]
            }
        )
    return FakeResponse(
        {
            "results": [
                {
                    "address_components": [
                        {"long_name": "Bengaluru", "types": ["locality"]},
                    ],
                    "formatted_address": "Bengaluru, Karnataka, India",
                }
            ]
        }
    )


def main() -> None:
    environment = {
        "GOOGLE_MAPS_API_KEY": "offline-test-key",
        "GOOGLE_MAPS_PLACES_ENABLED": "1",
        "SHOPPINGHELP_SEARCH_MODE": "live",
    }
    brief = {
        "category": "Office chair",
        "description": "ergonomic office chair",
        "occasion": "Office",
        "location": "Bengaluru",
    }
    with patch.dict(os.environ, environment, clear=False), patch("backend.location.urllib.request.urlopen", fake_urlopen):
        enriched, event = LocationAgent().run(
            brief,
            {"location_coordinates": {"latitude": 12.9716, "longitude": 77.5946}},
        )
    stores = enriched["location_context"]["nearby_stores"]
    assert event["status"] == "complete"
    assert enriched["location"] == "Bengaluru"
    assert stores[0]["name"] == "Example Furniture Hub"
    assert stores[0]["rating"] == 4.4
    serialized = json.dumps(enriched)
    assert "12.9716" not in serialized and "77.5946" not in serialized
    print("location_adapter_ok", stores[0]["name"])


if __name__ == "__main__":
    main()
