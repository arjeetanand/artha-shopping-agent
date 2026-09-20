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
            return {**brief, "location_source": "browser_permission (fixture; not persisted)"}, {
                "agent": self.name,
                "status": "complete",
                "detail": "Browser location permission received; fixture mode kept the location ephemeral",
            }
        try:
            label = _google_label(latitude, longitude)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
            label = None
        if label:
            return {**brief, "location": label, "location_source": "Google Maps geocoding (coordinates not persisted)"}, {
                "agent": self.name,
                "status": "complete",
                "detail": f"Google Maps resolved the permissioned location to {label}; precise coordinates were not persisted",
            }
        detail = "Browser coordinates received, but Maps geocoding is not configured; keep the typed delivery city for accuracy"
        if is_production():
            detail = "Location permission received; Maps geocoding is unavailable, so Artha kept the typed delivery city"
        return {**brief, "location_source": "browser_permission (unresolved; not persisted)"}, {
            "agent": self.name,
            "status": "waiting",
            "detail": detail,
        }
