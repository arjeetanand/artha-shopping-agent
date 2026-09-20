from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import ipaddress
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from .clients import AnakinClient, BriefModel, parse_price
from .catalog import FixtureCatalogClient
from .db import db, now_iso
from .location import LocationAgent
from .settings import setting


MAX_REFERENCE_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_REFERENCE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _money(value: int | float | str | None) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return parse_price(str(value or "")) or 0


def _date_label(days: int) -> str:
    target = date.today() + timedelta(days=max(days, 0))
    return target.strftime("%a")


def _parse_budget(text: str) -> int | None:
    match = re.search(r"(?:under|below|within|budget|less than|upto|up to)\D{0,12}(?:₹|rs\.?|inr)?\s*([\d,]+)", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)", text, flags=re.IGNORECASE)
    try:
        return int(match.group(1).replace(",", "")) if match else None
    except ValueError:
        return None


def _parse_days(text: str) -> int | None:
    match = re.search(r"(?:within|in|before)\s*(\d+)\s*days?", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _parse_quantity(text: str) -> int:
    match = re.search(r"\b(\d{1,3})(?:\s+[a-z][a-z0-9&'-]*){0,3}\s+(?:units?|items?|pieces?|pairs?|chairs?|shirts?)\b", text, flags=re.IGNORECASE)
    try:
        return max(1, min(int(match.group(1)), 99)) if match else 1
    except (AttributeError, ValueError):
        return 1


def _parse_brand(text: str) -> str | None:
    known_brands = ("worknest", "desktheory", "dailyseat", "luma office", "linen trail")
    lowered = text.lower()
    for brand in known_brands:
        if re.search(rf"\b{re.escape(brand)}\b", lowered):
            return brand.title() if brand != "luma office" else "Luma Office"
    match = re.search(
        r"(?:brand|from|by)\s+([a-z][a-z0-9&' -]{1,36}?)(?=\s+(?:under|below|for|in|within|delivered|with|and)\b|[,.;]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" .,'\"")
    return value[:60] if value else None


def _parse_specifications(text: str) -> list[str]:
    lowered = text.lower()
    known = [
        ("back support", ("back support", "lumbar", "ergonomic")),
        ("breathable", ("breathable", "mesh", "linen")),
        ("adjustable", ("adjustable", "height adjustable", "adjustable arms")),
        ("waterproof", ("waterproof", "water resistant")),
        ("neutral palette", ("neutral", "beige", "white", "black")),
        ("reclining", ("reclin", "tilt")),
    ]
    return [label for label, tokens in known if any(token in lowered for token in tokens)]


def _reference_image(payload: dict[str, Any]) -> dict[str, str] | None:
    """Validate a short-lived image payload without persisting its bytes."""
    value = payload.get("reference_image")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Reference image must be an object")
    mime_type = str(value.get("mime_type") or "").lower()
    encoded = str(value.get("data_base64") or "")
    if mime_type not in ALLOWED_REFERENCE_MIME_TYPES:
        raise ValueError("Reference images must be PNG, JPEG, WebP, or GIF")
    if not encoded:
        raise ValueError("Reference image data is missing")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Reference image data is invalid") from error
    if not raw or len(raw) > MAX_REFERENCE_IMAGE_BYTES:
        raise ValueError("Reference images must be 4 MB or smaller")
    return {
        "name": str(value.get("name") or "reference image")[:160],
        "mime_type": mime_type,
        "data_base64": encoded,
    }


def _reference_url(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    candidate = str(value).strip()
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("Reference URLs must be public http or https links")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("Reference URLs must use a public website")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise ValueError("Reference URLs must use a public website")
    return candidate


def _brief_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _brief_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or fallback
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return fallback


class BriefAgent:
    name = "Brief agent"

    def __init__(self) -> None:
        self.model = BriefModel()

    def run(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        text = str(payload.get("text") or payload.get("query") or "").strip()
        reference_image = _reference_image(payload)
        image_name = str(reference_image["name"] if reference_image else payload.get("image_name") or "").strip()
        if setting("SHOPPINGHELP_SEARCH_MODE", "live").lower() in {"fixture", "sandbox", "mock"}:
            lowered = text.lower()
            budget = _parse_budget(text) or 18000
            arrive_days = _parse_days(text) or 5
            quantity = _parse_quantity(text)
            brand = _parse_brand(text)
            if "chair" in lowered:
                category, occasion = "Office chair", "Office"
                must_have = _parse_specifications(text) or ["back support", "ergonomic"]
            elif any(word in lowered for word in ("shirt", "outfit", "dress", "shoe", "loafers")):
                category, occasion = "Clothing", "Everyday"
                must_have = _parse_specifications(text) or ["breathable", "neutral palette"]
            else:
                category, occasion = "Shopping", "Everyday"
                must_have = _parse_specifications(text)
            location_match = re.search(r"(?:deliver(?:ed|y)?\s+to|ship\s+to|in)\s+([a-z][a-z .'-]{2,40}?)(?:\s+within|\s+in\s+\d+\s+days|$)", text, flags=re.IGNORECASE)
            location = location_match.group(1).strip(" .,\"") if location_match else payload.get("location") or "Bengaluru"
            if str(location).lower() == "bangalore":
                location = "Bengaluru"
            brief = {
                "category": category,
                "occasion": occasion,
                "budget": budget,
                "quantity": quantity,
                "brand": brand,
                "location": location,
                "arrive_by_days": arrive_days,
                "arrive_by": f"within {arrive_days} days",
                "must_have": must_have,
                "specifications": must_have,
                "nice_to_have": ["durable", "good value"],
                "style": "practical and considered",
                "description": text or "Find a considered product",
                "raw_text": text or "Find a considered product",
                "image_name": image_name or None,
                "reference_image": {"name": image_name, "mime_type": reference_image["mime_type"]} if reference_image else None,
                "post_url": payload.get("post_url") or None,
                "extraction_source": "local fixture rules",
            }
            return brief, {"agent": self.name, "status": "complete", "detail": "Local fixture rules extracted price, place, delivery, and must-haves"}
        llm_brief, provider = self.model.extract_brief(text, reference_image)
        provider_status = self.model.status()
        if not provider_status["configured"]:
            raise RuntimeError(f"{provider.title()} brief extraction is not configured. Check its server credentials and settings.")
        if not llm_brief:
            raise RuntimeError(f"{provider.title()} brief extraction did not return a usable brief. Check the provider and try again.")
        fallback_budget = _parse_budget(text) or 18000
        fallback_days = _parse_days(text) or 5
        source = llm_brief or {}
        source_budget = _money(source.get("budget"))
        source_quantity = _money(source.get("quantity"))
        source_arrive_by_days = source.get("arrive_by_days")
        source_location = _brief_text(source.get("location"))
        if source_location.lower() in {"", "any", "any retail location", "unknown", "none", "null"}:
            source_location = ""
        source_category = _brief_text(source.get("category"))
        source_occasion = _brief_text(source.get("occasion"))
        source_arrive_by = _brief_text(source.get("arrive_by"))
        source_style = _brief_text(source.get("style"))
        source_description = _brief_text(source.get("description"))
        source_brand = _brief_text(source.get("brand"))
        source_specs = _brief_list(source.get("specifications"), [])
        source_must_have = _brief_list(source.get("must_have"), source_specs or ["breathable", "neutral palette", "office-ready"])
        brief = {
            "category": source_category or ("Fashion" if any(word in text.lower() for word in ["shirt", "pant", "shoe", "dress", "outfit", "look", "saree"]) else "Shopping"),
            "occasion": source_occasion or ("Office" if "office" in text.lower() else "Everyday"),
            "budget": source_budget or fallback_budget,
            "quantity": max(1, min(source_quantity or _parse_quantity(text), 99)),
            "brand": source_brand or _parse_brand(text),
            "location": source_location or payload.get("location") or "Bengaluru",
            "arrive_by_days": _money(source_arrive_by_days) if source_arrive_by_days is not None and source_arrive_by_days != "" else fallback_days,
            "arrive_by": source_arrive_by or f"within {fallback_days} days",
            "must_have": source_must_have,
            "specifications": source_specs or source_must_have,
            "nice_to_have": _brief_list(source.get("nice_to_have"), ["durable", "easy to layer"]),
            "style": source_style or "quietly considered",
            "description": source_description or text or "An office-ready neutral outfit",
            "raw_text": text or "Find an office-ready look under ₹18,000",
            "image_name": image_name or None,
            "reference_image": {"name": image_name, "mime_type": reference_image["mime_type"]} if reference_image else None,
            "post_url": payload.get("post_url") or None,
            "extraction_source": provider if llm_brief else "local rules",
        }
        if llm_brief and reference_image:
            detail = f"{provider.title()} analyzed the brief and reference image"
        elif llm_brief:
            detail = f"{provider.title()} extracted the brief"
        elif reference_image:
            detail = "Reference image attached; local rules extracted the typed brief"
        else:
            detail = "Local rules extracted price, place, and preferences"
        return brief, {"agent": self.name, "status": "complete", "detail": detail}


class SearchAgent:
    name = "Search agent"

    def __init__(self) -> None:
        self.anakin = AnakinClient()

    def run(self, brief: dict[str, Any], post_url: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        search_mode = setting("SHOPPINGHELP_SEARCH_MODE", "live").lower()
        if search_mode in {"fixture", "sandbox", "mock"}:
            response = FixtureCatalogClient().search(brief, num_results=10)
            sources = response.get("results") or []
            return (
                sources,
                {"agent": self.name, "status": "complete", "detail": f"Local catalog returned {len(sources)} constraint-test sources"},
                {"mode": "sandbox", "provider": "fixture_catalog", "scrape": "not_requested"},
            )
        if not self.anakin.configured:
            raise RuntimeError("Anakin live extraction is not configured. Add ANAKIN_API_KEY and restart the API.")
        source_context = ""
        scrape_status = "not_requested"
        if post_url:
            try:
                scraped = self.anakin.scrape_inline(post_url)
                source_context = str(scraped.get("markdown") or scraped.get("content") or scraped.get("generatedJson") or "")[:900]
                scrape_status = "complete" if source_context else "empty"
            except Exception:
                # A single source page should not prevent the user from receiving
                # a live cross-store search. The UI records that the page itself
                # could not be used as evidence.
                scrape_status = "unavailable"
        try:
            query = (
                f"Find purchasable {brief['category']} products in India for {brief['description']}. "
                f"Quantity {brief.get('quantity') or 1}; preferred brand {brief.get('brand') or 'any'}; "
                f"must-have specifications {', '.join(brief.get('must_have') or []) or 'none'}. "
                f"Budget ₹{brief['budget']}; deliver to {brief['location']} {brief['arrive_by']}. "
                "Prioritize official retailer product pages with price, availability, delivery and review evidence."
            )
            if source_context:
                query = f"{query} Reference context: {source_context}"
            response = self.anakin.search(query, num_results=10)
            sources = response.get("results") or response.get("data", {}).get("results") or []
            if isinstance(sources, list) and sources:
                detail = f"Anakin returned {len(sources)} live sources"
                if scrape_status == "complete":
                    detail = f"Anakin extracted the reference link and returned {len(sources)} live sources"
                elif scrape_status in {"empty", "unavailable"}:
                    detail = f"Anakin returned {len(sources)} live sources; the reference link could not be used"
                return sources, {"agent": self.name, "status": "complete", "detail": detail}, {"mode": "live", "scrape": scrape_status}
            raise RuntimeError("No usable live sources returned")
        except Exception as error:
            raise RuntimeError("Anakin live extraction did not return usable retailer sources. Check ANAKIN_API_KEY and network access.") from error


class ExtractionAgent:
    name = "Evidence agent"

    def _from_live(self, raw: dict[str, Any], index: int) -> dict[str, Any]:
        title = str(raw.get("title") or raw.get("name") or f"Live result {index + 1}")
        content = str(raw.get("content") or raw.get("snippet") or raw.get("description") or "")
        generated = raw.get("generatedJson") or raw.get("data") or {}
        data = generated.get("data") if isinstance(generated, dict) and isinstance(generated.get("data"), dict) else generated
        if not isinstance(data, dict) or not data:
            data = raw
        if isinstance(data, dict):
            title = str(data.get("name") or data.get("title") or title)
            content = str(data.get("description") or data.get("summary") or content)
        raw_price = data.get("price") if isinstance(data, dict) else None
        price = _money(raw_price) or parse_price(f"{title} {content}") or 0
        url = str(raw.get("url") or raw.get("link") or "")
        host = re.sub(r"^www\.", "", urlparse(url).netloc).split(":")[0] if url else "Web source"
        shipping_cost = _money(data.get("shipping_cost")) if isinstance(data, dict) else 0
        delivery_days = data.get("delivery_days") if isinstance(data, dict) else None
        try:
            delivery_days = int(delivery_days) if delivery_days is not None else None
        except (TypeError, ValueError):
            delivery_days = None
        source_kind = str(raw.get("source_kind") or "live_web")
        return {
            "id": str(raw.get("id") or f"live-{index}-{hashlib.sha1((url or title).encode()).hexdigest()[:8]}"),
            "name": title[:180],
            "category": str(data.get("category") if isinstance(data, dict) and data.get("category") else "Product"),
            "brand": str(data.get("brand") if isinstance(data, dict) and data.get("brand") else ""),
            "description": content[:180] or "Live retailer result. Confirm current price and delivery on the source page.",
            "seller": str(data.get("seller") if isinstance(data, dict) and data.get("seller") else host.title()),
            "price": price,
            "shipping_cost": shipping_cost,
            "total_price": price + shipping_cost,
            "rating": data.get("rating") if isinstance(data, dict) else 0,
            "delivery_days": delivery_days,
            "delivery_label": str(data.get("delivery_label") if isinstance(data, dict) and data.get("delivery_label") else "Confirm at retailer"),
            "stock": data.get("stock") if isinstance(data, dict) else None,
            "features": data.get("features") if isinstance(data, dict) and isinstance(data.get("features"), list) else [],
            "match_reasons": data.get("match_reasons") if isinstance(data, dict) and isinstance(data.get("match_reasons"), list) else ["Source linked"],
            "crop_index": index % 3,
            "url": url,
            "image": str(data.get("image") if isinstance(data, dict) else ""),
            "source_kind": source_kind,
            "source_label": str(raw.get("source_label") or ("Live retailer source" if source_kind == "live_web" else "Catalog source")),
            "evidence": data.get("evidence") if isinstance(data, dict) and isinstance(data.get("evidence"), list) else ["Source-linked product data", "Confirm seller checkout details"],
            "review_summary": str(data.get("review_summary") or "Review evidence requires retailer confirmation") if isinstance(data, dict) else "Review evidence requires retailer confirmation",
            "review_reliability": data.get("review_reliability") if isinstance(data, dict) else None,
            "review_sources": data.get("review_sources") if isinstance(data, dict) and isinstance(data.get("review_sources"), list) else [],
            "review_analysis": data.get("review_analysis") if isinstance(data, dict) and isinstance(data.get("review_analysis"), dict) else {},
            "price_history": data.get("price_history") if isinstance(data, dict) and isinstance(data.get("price_history"), dict) else {},
            "seller_reliability": data.get("seller_reliability") if isinstance(data, dict) else None,
        }

    def run(self, raw_products: list[dict[str, Any]], source_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if source_meta.get("mode") not in {"live", "sandbox"}:
            raise RuntimeError("A configured retailer source is required to build a purchase shortlist.")
        products = [self._from_live(raw, index) for index, raw in enumerate(raw_products) if isinstance(raw, dict)]
        if not products:
            raise RuntimeError("Anakin returned no usable retailer fields for this brief.")
        detail = "Normalized local catalog fields and constraint evidence" if source_meta.get("mode") == "sandbox" else "Normalized live source fields and retailer evidence"
        return products[:10], {"agent": self.name, "status": "complete", "detail": detail}


class AnalysisAgent:
    """Derive transparent review and price signals without filling unknowns."""

    name = "Analysis agent"

    @staticmethod
    def _review_signal(product: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
        sources = [source for source in (product.get("review_sources") or []) if isinstance(source, dict)]
        existing = product.get("review_reliability")
        try:
            reliability = float(existing) if existing is not None else None
        except (TypeError, ValueError):
            reliability = None
        if not sources:
            return reliability, product.get("review_analysis") if isinstance(product.get("review_analysis"), dict) else {}

        if reliability is None and len(sources) < 2:
            return None, {
                "label": "Single-source review metadata",
                "detail": "A retailer exposed review metadata, but an independent source was not available for authenticity cross-checking.",
                "caution_flags": 1,
            }

        signal_text = " ".join(str(source.get("signal") or "") for source in sources).lower()
        caution_terms = ("duplicate", "repeated", "anomaly", "limited", "small sample", "inconsistent")
        caution_count = sum(signal_text.count(term) for term in caution_terms)
        sample_count = sum(_money(source.get("count")) for source in sources)
        base = reliability if reliability is not None else 0.68
        base += min(0.08, max(0, len(sources) - 1) * 0.04)
        base += min(0.06, sample_count / 3000)
        base -= min(0.16, caution_count * 0.04)
        base = max(0.35, min(0.98, base))
        if caution_count >= 2:
            label = "Review signal needs caution"
        elif caution_count:
            label = "Mostly consistent"
        else:
            label = "Strong signal"
        detail = f"Compared {len(sources)} review sources ({sample_count or 'unknown'} sampled reviews); repeated-language flags are treated as caution, not proof of fake reviews."
        return round(base, 2), {"label": label, "detail": detail, "caution_flags": caution_count}

    @staticmethod
    def _price_signal(product: dict[str, Any]) -> dict[str, Any]:
        history = product.get("price_history") if isinstance(product.get("price_history"), dict) else {}
        if not history:
            return {}
        current = _money(product.get("price"))
        low = _money(history.get("low_90d"))
        median = _money(history.get("median_90d"))
        high = _money(history.get("high_90d"))
        if not current or not median:
            return history
        if low and current <= low * 1.03:
            label, score = "Near its 90-day low", 0.95
        elif current < median:
            label, score = "Below its 90-day median", 0.75
        elif high and current >= high * 0.97:
            label, score = "Near its 90-day high", 0.25
        else:
            label, score = "Typical 90-day price", 0.5
        return {**history, "low_90d": low or history.get("low_90d"), "median_90d": median, "high_90d": high or history.get("high_90d"), "trend_label": history.get("trend_label") or label, "deal_score": score}

    def run(self, products: list[dict[str, Any]], brief: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        review_known = 0
        price_known = 0
        for product in products:
            reliability, review_analysis = self._review_signal(product)
            if reliability is not None:
                product["review_reliability"] = reliability
                review_known += 1
            if review_analysis:
                product["review_analysis"] = review_analysis
            price_history = self._price_signal(product)
            if price_history:
                product["price_history"] = price_history
                price_known += 1
        return products, {
            "agent": self.name,
            "status": "complete",
            "detail": f"Cross-checked review consistency ({review_known} sources) and price history ({price_known} products); unknown signals remain unverified",
        }


def _scraped_mapping(value: Any) -> dict[str, Any]:
    """Extract a safe structured mapping from an Anakin scrape response."""
    if isinstance(value, dict):
        for key in ("generatedJson", "generated_json", "product", "result"):
            nested = value.get(key)
            if isinstance(nested, dict):
                return _scraped_mapping(nested)
            if isinstance(nested, str):
                parsed = _scraped_mapping(nested)
                if parsed:
                    return parsed
        data = value.get("data")
        if isinstance(data, dict) and data:
            nested = _scraped_mapping(data)
            return nested or data
        return value
    if isinstance(value, str):
        candidate = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if not candidate.startswith("{"):
            return {}
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _scraped_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    chunks = []
    for key in ("markdown", "content", "text", "description", "summary"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            chunks.append(item.strip())
    return " ".join(chunks)[:12000]


class ResearchAgent:
    """Parallel direct-page checks for live product evidence.

    The agent only fills missing structured fields or records a transparent
    mismatch. It never turns unstructured page copy into a verified price,
    stock, review, or seller claim.
    """

    name = "Research agent"

    def __init__(self) -> None:
        self.anakin = AnakinClient()

    @staticmethod
    def _host(url: str) -> str:
        return re.sub(r"^www\.", "", urlparse(url).netloc).split(":")[0] or "product page"

    @staticmethod
    def _review_source(product: dict[str, Any], data: dict[str, Any], text: str, host: str) -> dict[str, Any] | None:
        sources = data.get("review_sources") if isinstance(data.get("review_sources"), list) else []
        if sources:
            candidate = sources[0] if isinstance(sources[0], dict) else {}
            return {
                "name": str(candidate.get("name") or f"{host} retailer reviews")[:120],
                "count": _money(candidate.get("count")) or None,
                "rating": candidate.get("rating"),
                "signal": str(candidate.get("signal") or "Direct retailer page; independent corroboration unavailable")[:180],
            }
        count_match = re.search(r"(\d[\d,]*)\s+(?:verified\s+)?(?:customer\s+)?(?:reviews|ratings)\b", text, flags=re.IGNORECASE)
        rating_match = re.search(r"\b([0-5](?:\.[0-9])?)\s*(?:/\s*5|out of 5|stars?)\b", text, flags=re.IGNORECASE)
        if not count_match and not rating_match:
            return None
        return {
            "name": f"{host} retailer reviews"[:120],
            "count": int(count_match.group(1).replace(",", "")) if count_match else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "signal": "Direct retailer page; limited independent corroboration",
        }

    def _one(self, product: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        enriched = copy.deepcopy(product)
        url = str(enriched.get("url") or "")
        host = self._host(url)
        if not url:
            enriched["research_status"] = "waiting"
            enriched["research_sources"] = [{"name": "Product URL", "status": "missing", "detail": "No public product page was returned"}]
            return enriched, False
        try:
            scraped = self.anakin.scrape_inline(url)
        except Exception:
            enriched["research_status"] = "waiting"
            enriched["research_sources"] = [{"name": host, "status": "unavailable", "detail": "Direct page research could not be completed"}]
            return enriched, False

        data = _scraped_mapping(scraped)
        text = _scraped_text(scraped)
        evidence = [str(item) for item in (enriched.get("evidence") or []) if str(item).strip()]
        fields: list[str] = []
        for field in ("brand", "seller", "delivery_days", "delivery_label", "stock", "rating", "shipping_cost", "image", "seller_reliability"):
            value = data.get(field)
            if value in (None, "", [], {}):
                continue
            if enriched.get(field) in (None, "", [], {}):
                enriched[field] = value
                fields.append(field)

        scraped_price = _money(data.get("price"))
        current_price = _money(enriched.get("price"))
        if scraped_price and current_price and scraped_price != current_price:
            enriched["price_verification"] = "mismatch"
            evidence.append(f"Search price {current_price} differs from direct page price {scraped_price}; confirm at checkout")
        elif scraped_price and not current_price:
            enriched["price"] = scraped_price
            fields.append("price")

        for field in ("features", "review_sources", "price_history"):
            value = data.get(field)
            if value and not enriched.get(field):
                enriched[field] = value
                fields.append(field)

        review_source = self._review_source(enriched, data, text, host)
        if review_source:
            existing_sources = [source for source in (enriched.get("review_sources") or []) if isinstance(source, dict)]
            if not any(str(source.get("name") or "").lower() == review_source["name"].lower() for source in existing_sources):
                existing_sources.append(review_source)
            enriched["review_sources"] = existing_sources[:6]
            fields.append("review metadata")

        enriched["research_status"] = "complete"
        enriched["research_sources"] = [{"name": host, "status": "complete", "detail": "Direct product page checked", "fields": fields[:8]}]
        evidence.append(f"Direct product page checked on {host}")
        enriched["evidence"] = list(dict.fromkeys(evidence))[:10]
        return enriched, True

    def run(self, products: list[dict[str, Any]], source_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        mode = str(source_meta.get("mode") or "").lower()
        if mode == "sandbox":
            for product in products:
                product["research_status"] = "complete"
                product["research_sources"] = [{"name": str(product.get("source_label") or "Local catalog"), "status": "catalog", "detail": "Deterministic local evidence"}]
            source_meta["research"] = {"mode": "fixture", "attempted": len(products), "completed": len(products)}
            return products, {"agent": self.name, "status": "complete", "detail": "Local catalog evidence already includes seller, review, stock, and price signals"}, source_meta

        candidate_entries = [(index, product) for index, product in enumerate(products) if str(product.get("url") or "")][:6]
        candidates = [product for _, product in candidate_entries]
        if not candidates:
            source_meta["research"] = {"mode": "parallel_url_scrape", "attempted": 0, "completed": 0}
            return products, {"agent": self.name, "status": "waiting", "detail": "No public product URLs were returned for direct research"}, source_meta

        enriched = list(products)
        completed = 0
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as executor:
            futures = {executor.submit(self._one, product): index for index, product in candidate_entries}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    product, ok = future.result()
                except Exception:
                    product, ok = copy.deepcopy(candidates[index]), False
                    product["research_status"] = "waiting"
                enriched[index] = product
                completed += int(ok)
        source_meta["research"] = {"mode": "parallel_url_scrape", "attempted": len(candidates), "completed": completed}
        status = "complete" if completed else "waiting"
        detail = f"Parallel direct-page checks completed for {completed}/{len(candidates)} products; missing fields remain unverified"
        return enriched, {"agent": self.name, "status": status, "detail": detail}, source_meta


class RankingAgent:
    name = "Decision agent"

    def run(self, products: list[dict[str, Any]], brief: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        budget = max(_money(brief.get("budget")), 1)
        max_days = brief.get("arrive_by_days") or 5
        quantity = max(1, min(_money(brief.get("quantity")) or 1, 99))
        requested_brand = str(brief.get("brand") or "").strip().lower()
        ranked: list[dict[str, Any]] = []
        for product in products:
            features = " ".join(product.get("features") or []).lower()
            must_have = [str(item).lower() for item in (brief.get("must_have") or [])]
            feature_score = sum(1 for item in must_have if item in features or all(token in features for token in item.split())) / max(len(must_have), 1)
            price = _money(product.get("price"))
            shipping_cost = _money(product.get("shipping_cost"))
            total_price = _money(product.get("total_price")) or price + shipping_cost
            product["shipping_cost"] = shipping_cost
            product["total_price"] = total_price or None
            product["quantity"] = quantity
            product["unit_total"] = total_price or None
            product["line_total"] = total_price * quantity if total_price else None
            delivery = product.get("delivery_days")
            line_total = product.get("line_total")
            budget_score = max(0, min(1, 1 - max(line_total - budget, 0) / budget)) if line_total else 0.35
            delivery_score = 0.35 if delivery is None else max(0, min(1, 1 - max(delivery - max_days, 0) / max(max_days, 1)))
            deal_score = product.get("price_history", {}).get("deal_score") if isinstance(product.get("price_history"), dict) else None
            deal_bonus = max(0, min(5, round(float(deal_score or 0) * 5)))
            product_text = " ".join(str(product.get(field) or "") for field in ("brand", "seller", "name")).lower()
            brand_fit = True if not requested_brand else requested_brand in product_text
            stock_value = product.get("stock")
            stock_known = stock_value is not None and str(stock_value).strip() != ""
            stock_match = re.search(r"\d+", str(stock_value)) if stock_known else None
            stock_count = int(stock_match.group(0)) if stock_match else None
            stock_fit = stock_count >= quantity if stock_count is not None else None
            brand_bonus = 8 if brand_fit and requested_brand else -8 if requested_brand else 0
            stock_bonus = 4 if stock_fit is True else -8 if stock_fit is False else 0
            seller_reliability = product.get("seller_reliability")
            try:
                seller_reliability = float(seller_reliability) if seller_reliability is not None else None
            except (TypeError, ValueError):
                seller_reliability = None
            seller_bonus = 3 if seller_reliability is not None and seller_reliability >= 0.8 else -3 if seller_reliability is not None and seller_reliability < 0.5 else 0
            match_score = round(55 + feature_score * 20 + budget_score * 15 + delivery_score * 10 + deal_bonus + brand_bonus + stock_bonus + seller_bonus)
            product["match_score"] = min(99, max(42, match_score))
            product["budget_fit"] = line_total <= budget if line_total else None
            product["delivery_fit"] = delivery <= max_days if delivery is not None else None
            product["brand_fit"] = brand_fit if requested_brand else None
            product["stock_fit"] = stock_fit
            product["delivery_label"] = product.get("delivery_label") or (f"Arrives {_date_label(delivery)}" if delivery else "Confirm at retailer")
            product["reason_tags"] = [
                "Within budget" if product["budget_fit"] is True else "Over budget" if product["budget_fit"] is False else "Price needs confirmation",
                "Within delivery window" if product["delivery_fit"] is True else "Misses delivery window" if product["delivery_fit"] is False else "Delivery needs confirmation",
                f"{quantity} in stock" if stock_fit is True and quantity > 1 else "Stock covers quantity" if stock_fit is True else f"Only {stock_count} in stock" if stock_fit is False else "Availability needs confirmation",
                "Seller signal available" if seller_reliability is not None else "Seller reliability needs confirmation",
            ]
            if requested_brand:
                product["reason_tags"].append("Preferred brand" if brand_fit else "Brand preference not met")
            product["eligible"] = product["budget_fit"] is not False and product["delivery_fit"] is not False and product["stock_fit"] is not False
            ranked.append(product)
        ranked.sort(key=lambda item: (not item.get("eligible", True), -item.get("match_score", 0), item.get("line_total") or 10**9))
        return ranked, {"agent": self.name, "status": "complete", "detail": "Ranked by fit, budget, delivery, and source evidence"}


def _default_selection(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [
        product
        for product in products
        if product.get("budget_fit") is not False and product.get("delivery_fit") is not False
    ]
    candidates = [product for product in eligible if _money(product.get("price")) > 0] or eligible or products
    chosen: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    for product in candidates:
        category = str(product.get("category") or "product").lower()
        if category in seen_categories:
            continue
        chosen.append(product)
        seen_categories.add(category)
        if len(chosen) == 3:
            return chosen
    chosen_ids = {product["id"] for product in chosen}
    chosen.extend(product for product in candidates if product["id"] not in chosen_ids and len(chosen) < 3)
    return chosen


def _merge_refinement_intent(previous: dict[str, Any], text: str) -> dict[str, Any]:
    brief = copy.deepcopy(previous)
    follow_up = str(text or "").strip()
    lowered = follow_up.lower()
    if not follow_up:
        return brief

    delta_match = re.search(r"(?:increase|raise|add|extra|more)\D{0,18}(?:₹|rs\.?|inr)?\s*([\d,]+)", follow_up, flags=re.IGNORECASE)
    explicit_budget = _parse_budget(follow_up)
    if delta_match and any(term in lowered for term in ("budget", "spend", "pay", "price")):
        brief["budget"] = _money(brief.get("budget")) + int(delta_match.group(1).replace(",", ""))
    elif explicit_budget and any(term in lowered for term in ("under", "below", "within", "budget", "upto", "up to")):
        brief["budget"] = explicit_budget

    quantity_match = re.search(r"\b(\d{1,3})(?:\s+[a-z][a-z0-9&'-]*){0,3}\s+(?:units?|items?|pieces?|pairs?|chairs?|shirts?)\b", follow_up, flags=re.IGNORECASE)
    if quantity_match:
        brief["quantity"] = max(1, min(int(quantity_match.group(1)), 99))
    brand = _parse_brand(follow_up)
    if brand:
        brief["brand"] = brand
    if _parse_days(follow_up) is not None:
        days = _parse_days(follow_up) or brief.get("arrive_by_days") or 5
        brief["arrive_by_days"] = days
        brief["arrive_by"] = f"within {days} days"
    location_match = re.search(r"(?:deliver(?:ed|y)?\s+to|ship\s+to|in)\s+([a-z][a-z .'-]{2,40}?)(?:\s+within|\s+in\s+\d+\s+days|$)", follow_up, flags=re.IGNORECASE)
    if location_match:
        location = location_match.group(1).strip(" .,\"")
        brief["location"] = "Bengaluru" if location.lower() == "bangalore" else location
    new_specs = _parse_specifications(follow_up)
    if new_specs:
        existing_specs = _brief_list(brief.get("must_have"), [])
        brief["must_have"] = list(dict.fromkeys(existing_specs + new_specs))
        brief["specifications"] = brief["must_have"]
    if any(term in lowered for term in ("cheaper", "lower price", "save money", "less expensive")):
        brief["nice_to_have"] = list(dict.fromkeys(_brief_list(brief.get("nice_to_have"), []) + ["lower total cost"]))
    brief["raw_text"] = f"{brief.get('raw_text') or brief.get('description') or ''} Follow-up: {follow_up}".strip()
    brief["description"] = f"{brief.get('description') or ''}. Follow-up preference: {follow_up}".strip(". ")
    brief["follow_up"] = follow_up
    brief["extraction_source"] = f"{brief.get('extraction_source') or 'existing research'} + follow-up refinement"
    return brief


def run_refinement(payload: dict[str, Any]) -> dict[str, Any]:
    previous_intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    previous_products = payload.get("products") if isinstance(payload.get("products"), list) else []
    text = str(payload.get("text") or payload.get("query") or "").strip()
    if not previous_intent or not previous_products:
        raise ValueError("A previous search is required before refining the shortlist")
    if not text:
        raise ValueError("Tell Artha what you would like to change")
    brief = _merge_refinement_intent(previous_intent, text)
    products = copy.deepcopy([product for product in previous_products if isinstance(product, dict)])
    products, analysis_event = AnalysisAgent().run(products, brief)
    products, ranking_event = RankingAgent().run(products, brief)
    search_id = f"search-{uuid.uuid4().hex[:12]}"
    follow_up_event = {
        "agent": "Follow-up agent",
        "status": "complete",
        "detail": "Kept the completed research set and applied the new preference without repeating retailer discovery",
    }
    workflow = [follow_up_event, analysis_event, ranking_event]
    db.save_search(search_id, brief["raw_text"], brief, workflow, products=products)
    selected_products = _default_selection(products)
    latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 5
    source = copy.deepcopy(payload.get("source")) if isinstance(payload.get("source"), dict) else {"mode": "refined"}
    source["refined"] = True
    return {
        "search_id": search_id,
        "intent": brief,
        "products": products,
        "selected_product_ids": [product["id"] for product in selected_products],
        "summary": {
            "total": sum(_money(product.get("line_total")) or _money(product.get("total_price")) for product in selected_products),
            "item_count": len(selected_products),
            "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer",
        },
        "workflow": workflow,
        "source": source,
        "conversation": [
            {"role": "user", "text": text},
            {"role": "assistant", "text": "I kept the completed research and updated the shortlist with that preference."},
        ],
    }


WORKFLOW_AGENTS = (
    "Brief agent",
    "Location agent",
    "Search agent",
    "Evidence agent",
    "Research agent",
    "Analysis agent",
    "Decision agent",
)


def initial_workflow() -> list[dict[str, Any]]:
    return [
        {"agent": "Brief agent", "status": "queued", "detail": "Waiting to extract your shopping requirements"},
        {"agent": "Location agent", "status": "queued", "detail": "Using your typed delivery location or optional permission"},
        {"agent": "Search agent", "status": "queued", "detail": "Waiting to query retailer sources"},
        {"agent": "Evidence agent", "status": "queued", "detail": "Source evidence will be normalized after discovery"},
        {"agent": "Research agent", "status": "queued", "detail": "Parallel product-page checks will validate seller and review signals"},
        {"agent": "Analysis agent", "status": "queued", "detail": "Review and price signals will be cross-checked"},
        {"agent": "Decision agent", "status": "queued", "detail": "Recommendations will be ranked against your constraints"},
    ]


def run_search(payload: dict[str, Any], progress: Callable[[list[dict[str, Any]]], None] | None = None) -> dict[str, Any]:
    workflow = initial_workflow()

    def emit() -> None:
        if progress:
            try:
                progress(copy.deepcopy(workflow))
            except Exception:
                pass

    def set_stage(index: int, status: str, detail: str) -> None:
        workflow[index] = {"agent": WORKFLOW_AGENTS[index], "status": status, "detail": detail}
        emit()

    post_url = _reference_url(payload.get("post_url"))
    agent_payload = dict(payload)
    agent_payload["post_url"] = post_url
    set_stage(0, "working", "Extracting category, budget, quantity, location, and preferences")
    brief, brief_event = BriefAgent().run(agent_payload)
    workflow[0] = brief_event
    emit()
    set_stage(1, "working", "Checking typed delivery location and optional browser permission")
    brief, location_event = LocationAgent().run(brief, payload)
    workflow[1] = location_event
    emit()
    set_stage(2, "working", "Searching retailer sources and reference context")
    raw_products, search_event, source_meta = SearchAgent().run(brief, post_url)
    workflow[2] = search_event
    emit()
    set_stage(3, "working", "Normalizing price, stock, delivery, seller, and review evidence")
    products, evidence_event = ExtractionAgent().run(raw_products, source_meta)
    workflow[3] = evidence_event
    emit()
    set_stage(4, "working", "Checking direct product pages in parallel")
    products, research_event, source_meta = ResearchAgent().run(products, source_meta)
    workflow[4] = research_event
    emit()
    set_stage(5, "working", "Cross-checking review and price-history signals")
    products, analysis_event = AnalysisAgent().run(products, brief)
    workflow[5] = analysis_event
    emit()
    set_stage(6, "working", "Ranking options against every stated constraint")
    products, ranking_event = RankingAgent().run(products, brief)
    workflow[6] = ranking_event
    emit()
    search_id = f"search-{uuid.uuid4().hex[:12]}"
    db.save_search(search_id, brief["raw_text"], brief, workflow, products=products)
    selected_products = _default_selection(products)
    total = sum(_money(product.get("line_total")) or _money(product.get("total_price")) or _money(product.get("price")) for product in selected_products)
    latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 5
    return {
        "search_id": search_id,
        "intent": brief,
        "products": products,
        "selected_product_ids": [product["id"] for product in selected_products],
        "summary": {"total": total, "item_count": len(selected_products), "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer"},
        "workflow": workflow,
        "source": source_meta,
        "conversation": [{"role": "user", "text": brief["raw_text"]}],
    }


def _safe_plan_item(product: dict[str, Any]) -> dict[str, Any]:
    url = str(product.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        url = ""
    item_price = _money(product.get("price"))
    shipping_cost = _money(product.get("shipping_cost"))
    total_price = _money(product.get("total_price")) or item_price + shipping_cost
    quantity = max(1, min(_money(product.get("quantity")) or 1, 99))
    line_total = _money(product.get("line_total")) or total_price * quantity
    return {
        "id": str(product.get("id") or uuid.uuid4().hex),
        "name": str(product.get("name") or "Retailer product")[:180],
        "seller": str(product.get("seller") or "Retailer")[:100],
        "brand": str(product.get("brand") or "")[:100],
        "quantity": quantity,
        "price": item_price,
        "shipping_cost": shipping_cost,
        "total_price": total_price,
        "unit_total": total_price,
        "line_total": line_total,
        "delivery_label": str(product.get("delivery_label") or "Confirm at retailer")[:120],
        "url": url,
        "image": str(product.get("image") or ""),
        "crop_index": _money(product.get("crop_index")),
        "source_kind": str(product.get("source_kind") or "source"),
        "review_summary": str(product.get("review_summary") or "Review evidence requires retailer confirmation")[:240],
        "review_reliability": product.get("review_reliability"),
        "seller_reliability": product.get("seller_reliability"),
        "research_status": str(product.get("research_status") or "unverified")[:24],
        "research_sources": [
            {
                "name": str(source.get("name") or "Research source")[:120],
                "status": str(source.get("status") or "unknown")[:24],
                "detail": str(source.get("detail") or "Research detail unavailable")[:180],
            }
            for source in (product.get("research_sources") or [])
            if isinstance(source, dict)
        ][:6],
        "review_sources": [
            {
                "name": str(source.get("name") or "Review source")[:120],
                "count": _money(source.get("count")),
                "rating": source.get("rating"),
                "signal": str(source.get("signal") or "Signal requires confirmation")[:160],
            }
            for source in (product.get("review_sources") or [])
            if isinstance(source, dict)
        ][:6],
        "review_analysis": product.get("review_analysis") if isinstance(product.get("review_analysis"), dict) else {},
        "price_history": product.get("price_history") if isinstance(product.get("price_history"), dict) else {},
        "evidence": [str(item)[:180] for item in (product.get("evidence") or []) if str(item).strip()][:8],
    }


def create_purchase_plan(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    products = [_safe_plan_item(product) for product in (payload.get("products") or []) if isinstance(product, dict)]
    products = [product for product in products if product["url"]]
    if not products:
        raise ValueError("Select at least one linked retailer product before saving a purchase plan")
    timestamp = now_iso()
    plan = {
        "id": f"PLAN-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}",
        "user_id": user_id,
        "search_id": payload.get("search_id"),
        "status": "ready_for_checkout",
        "total": sum(product["line_total"] for product in products),
        "items": products,
        "created_at": timestamp,
        "updated_at": timestamp,
        "notice": "Open each retailer link to complete checkout on that retailer's secure site. Artha never handles payment credentials.",
    }
    return db.save_purchase_plan(plan)
