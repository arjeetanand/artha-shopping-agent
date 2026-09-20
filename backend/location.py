"""Explicit, permission-based location enrichment for shopping briefs.

The browser only sends coordinates after the user taps the location control.
Production can enable Google Maps Geocoding with ``GOOGLE_MAPS_API_KEY``;
development keeps the coordinates ephemeral and never stores them in SQLite.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .settings import is_production, setting


def _coordinates(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        latitude = float(value.get("latitude"))
        longitude = float(value.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return round(latitude, 5), round(longitude, 5)


def _google_label(latitude: float, longitude: float) -> str | None:
    key = setting("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    query = urllib.parse.urlencode({"latlng": f"{latitude},{longitude}", "key": key, "language": "en"})
    request = urllib.request.Request(
        f"https://maps.googleapis.com/maps/api/geocode/json?{query}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8"))
    results = body.get("results") if isinstance(body, dict) else []
    if not isinstance(results, list) or not results:
        return None
    components = results[0].get("address_components") if isinstance(results[0], dict) else []
    for preferred_type in ("locality", "postal_town", "administrative_area_level_2"):
        for component in components or []:
            if preferred_type in (component.get("types") or []):
                return str(component.get("long_name") or "").strip() or None
    return str(results[0].get("formatted_address") or "").split(",")[0].strip() or None


def _store_type(brief: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        str(brief.get(field) or "")
        for field in ("category", "description", "occasion")
    ).lower()
    if any(term in text for term in ("chair", "desk", "furniture", "ergonomic")):
        return "furniture_store", "furniture store"
    if any(term in text for term in ("shirt", "clothing", "outfit", "fashion", "wear")):
        return "clothing_store", "clothing store"
    return "shopping_mall", "shopping mall"


def _place_record(place: dict[str, Any]) -> dict[str, Any] | None:
    display_name = place.get("displayName") if isinstance(place.get("displayName"), dict) else {}
    name = str(display_name.get("text") or place.get("name") or "").strip()
    address = str(place.get("formattedAddress") or place.get("vicinity") or "").strip()
    if not name:
        return None
    result: dict[str, Any] = {"name": name[:120], "address": address[:180]}
    rating = place.get("rating")
    if rating not in (None, ""):
        result["rating"] = rating
    review_count = place.get("userRatingCount", place.get("user_ratings_total"))
    if review_count not in (None, ""):
        result["review_count"] = review_count
    maps_url = place.get("googleMapsUri") or place.get("url")
    if maps_url:
        result["url"] = str(maps_url)[:500]
    return result


def _google_places(latitude: float, longitude: float, brief: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Return nearby store signals without returning or persisting raw coordinates."""
    key = setting("GOOGLE_MAPS_API_KEY")
    enabled = setting("GOOGLE_MAPS_PLACES_ENABLED", "1").lower() not in {"0", "false", "no"}
    if not key or not enabled:
        return [], None
    place_type, keyword = _store_type(brief)
    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": 5000,
            }
        },
    }
    try:
        request = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchNearby",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.googleMapsUri",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
        places = body.get("places") if isinstance(body, dict) else []
        records = [record for place in places or [] if isinstance(place, dict) for record in [_place_record(place)] if record]
        if records:
            return records[:5], "Google Places (coordinates not persisted)"
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
        pass

    # Keep a compatibility fallback for projects that have the legacy Places API
    # enabled while they migrate to Places API (New).
    try:
        query = urllib.parse.urlencode(
            {
                "location": f"{latitude},{longitude}",
                "radius": 5000,
                "keyword": keyword,
                "key": key,
                "language": "en",
            }
        )
        request = urllib.request.Request(
            f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?{query}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
        places = body.get("results") if isinstance(body, dict) else []
        records = [record for place in places or [] if isinstance(place, dict) for record in [_place_record(place)] if record]
        return records[:5], "Google Places (coordinates not persisted)" if records else None
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
        return [], None


class LocationAgent:
    name = "Location agent"

    def run(self, brief: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        coordinates = _coordinates(payload.get("location_coordinates"))
        if not coordinates:
            return brief, {
                "agent": self.name,
                "status": "complete",
                "detail": "Using the delivery location stated in the shopping brief",
            }
        latitude, longitude = coordinates
        if setting("SHOPPINGHELP_SEARCH_MODE", "live").lower() in {"fixture", "sandbox", "mock"}:
            return {
                **brief,
                "location_source": "browser_permission (fixture; not persisted)",
                "location_context": {"nearby_stores": [], "status": "not queried in fixture mode"},
            }, {
                "agent": self.name,
                "status": "complete",
                "detail": "Browser location permission received; fixture mode kept the location ephemeral",
            }
        stores, places_provider = _google_places(latitude, longitude, brief)
        context = {
            "nearby_stores": stores,
            "provider": places_provider,
            "status": "complete" if stores else "unavailable",
        }
        try:
            label = _google_label(latitude, longitude)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
            label = None
        enriched = {**brief, "location_context": context}
        if label:
            nearby_detail = f"; {len(stores)} nearby store signals checked" if stores else ""
            return {**enriched, "location": label, "location_source": "Google Maps geocoding (coordinates not persisted)"}, {
                "agent": self.name,
                "status": "complete",
                "detail": f"Google Maps resolved the permissioned location to {label}{nearby_detail}; precise coordinates were not persisted",
            }
        if stores:
            return {**enriched, "location_source": "browser_permission (nearby stores resolved; coordinates not persisted)"}, {
                "agent": self.name,
                "status": "complete",
                "detail": f"Google Places found {len(stores)} nearby store signals; typed delivery city retained and coordinates were not persisted",
            }
        detail = "Browser coordinates received, but Maps geocoding is not configured; keep the typed delivery city for accuracy"
        if is_production():
            detail = "Location permission received; Maps geocoding is unavailable, so Artha kept the typed delivery city"
        return {**enriched, "location_source": "browser_permission (unresolved; not persisted)"}, {
            "agent": self.name,
            "status": "waiting",
            "detail": detail,
        }
