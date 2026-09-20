from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from .catalog import CATALOG, IMAGE_PATH
from .clients import AnakinClient, BriefModel, parse_price
from .db import db, now_iso


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
        llm_brief, provider = self.model.extract_brief(text, reference_image)
        fallback_budget = _parse_budget(text) or 18000
        fallback_days = _parse_days(text) or 5
        source = llm_brief or {}
        source_budget = _money(source.get("budget"))
        source_arrive_by_days = source.get("arrive_by_days")
        source_location = _brief_text(source.get("location"))
        if source_location.lower() in {"", "any", "any retail location", "unknown", "none", "null"}:
            source_location = ""
        source_category = _brief_text(source.get("category"))
        source_occasion = _brief_text(source.get("occasion"))
        source_arrive_by = _brief_text(source.get("arrive_by"))
        source_style = _brief_text(source.get("style"))
        source_description = _brief_text(source.get("description"))
        brief = {
            "category": source_category or ("Fashion" if any(word in text.lower() for word in ["shirt", "pant", "shoe", "dress", "outfit", "look", "saree"]) else "Shopping"),
            "occasion": source_occasion or ("Office" if "office" in text.lower() else "Everyday"),
            "budget": source_budget or fallback_budget,
            "location": source_location or payload.get("location") or "Bengaluru",
            "arrive_by_days": _money(source_arrive_by_days) if source_arrive_by_days is not None and source_arrive_by_days != "" else fallback_days,
            "arrive_by": source_arrive_by or f"within {fallback_days} days",
            "must_have": _brief_list(source.get("must_have"), ["breathable", "neutral palette", "office-ready"]),
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
        if not self.anakin.configured:
            return CATALOG, {"agent": self.name, "status": "local", "detail": "Using the local development catalog"}, {"mode": "local", "scrape": False}
        try:
            source_context = ""
            if post_url:
                scraped = self.anakin.scrape_inline(post_url)
                source_context = str(scraped.get("markdown") or scraped.get("content") or scraped.get("generatedJson") or "")[:900]
            query = (
                f"Find purchasable {brief['category']} products in India for {brief['description']}. "
                f"Budget ₹{brief['budget']}; deliver to {brief['location']} {brief['arrive_by']}. "
                "Prioritize official retailer product pages with price, availability, delivery and review evidence."
            )
            if source_context:
                query = f"{query} Reference context: {source_context}"
            response = self.anakin.search(query, num_results=10)
            sources = response.get("results") or response.get("data", {}).get("results") or []
            if isinstance(sources, list) and sources:
                return sources, {"agent": self.name, "status": "complete", "detail": f"Anakin returned {len(sources)} live sources"}, {"mode": "live", "scrape": bool(post_url)}
            raise RuntimeError("No usable live sources returned")
        except Exception:
            return CATALOG, {"agent": self.name, "status": "fallback", "detail": "Live extraction was unavailable; using the local development catalog"}, {"mode": "local", "scrape": bool(post_url), "fallback": True}


class ExtractionAgent:
    name = "Evidence agent"

    def _from_live(self, raw: dict[str, Any], index: int) -> dict[str, Any]:
        title = str(raw.get("title") or raw.get("name") or f"Live result {index + 1}")
        content = str(raw.get("content") or raw.get("snippet") or raw.get("description") or "")
        generated = raw.get("generatedJson") or raw.get("data") or {}
        data = generated.get("data") if isinstance(generated, dict) and isinstance(generated.get("data"), dict) else generated
        if isinstance(data, dict):
            title = str(data.get("name") or data.get("title") or title)
            content = str(data.get("description") or data.get("summary") or content)
        raw_price = data.get("price") if isinstance(data, dict) else None
        price = _money(raw_price) or parse_price(f"{title} {content}") or 0
        url = str(raw.get("url") or raw.get("link") or "")
        host = re.sub(r"^www\.", "", urlparse(url).netloc).split(":")[0] if url else "Web source"
        return {
            "id": f"live-{index}-{hashlib.sha1((url or title).encode()).hexdigest()[:8]}",
            "name": title[:180],
            "category": str(data.get("category") if isinstance(data, dict) and data.get("category") else "Product"),
            "description": content[:180] or "Live retailer result. Confirm current price and delivery on the source page.",
            "seller": host.title(),
            "price": price,
            "rating": 0,
            "delivery_days": None,
            "delivery_label": "Confirm at retailer",
            "stock": None,
            "features": [],
            "match_reasons": ["Live retailer source", "Source linked"],
            "crop_index": index % 3,
            "url": url,
            "image": IMAGE_PATH,
            "source_kind": "live_web",
            "source_label": "Live retailer source",
            "evidence": ["Anakin live extraction", "Confirm seller checkout details"],
        }

    def run(self, raw_products: list[dict[str, Any]], source_meta: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if source_meta.get("mode") == "live":
            products = [self._from_live(raw, index) for index, raw in enumerate(raw_products) if isinstance(raw, dict)]
            if products:
                return products[:10], {"agent": self.name, "status": "complete", "detail": "Normalized live source fields and retailer evidence"}
        return [dict(product) for product in raw_products], {"agent": self.name, "status": "local", "detail": "Loaded structured fields from the local development catalog"}


class RankingAgent:
    name = "Decision agent"

    def run(self, products: list[dict[str, Any]], brief: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        budget = max(_money(brief.get("budget")), 1)
        max_days = brief.get("arrive_by_days") or 5
        ranked: list[dict[str, Any]] = []
        for product in products:
            features = " ".join(product.get("features") or []).lower()
            must_have = [str(item).lower() for item in (brief.get("must_have") or [])]
            feature_score = sum(1 for item in must_have if item in features) / max(len(must_have), 1)
            price = _money(product.get("price"))
            delivery = product.get("delivery_days")
            budget_score = max(0, min(1, 1 - max(price - budget, 0) / budget)) if price else 0.35
            delivery_score = 0.35 if delivery is None else max(0, min(1, 1 - max(delivery - max_days, 0) / max(max_days, 1)))
            match_score = round(58 + feature_score * 18 + budget_score * 14 + delivery_score * 10)
            product["match_score"] = min(99, max(42, match_score))
            product["budget_fit"] = price <= budget if price else None
            product["delivery_fit"] = delivery <= max_days if delivery is not None else None
            product["delivery_label"] = product.get("delivery_label") or (f"Arrives {_date_label(delivery)}" if delivery else "Confirm at retailer")
            product["reason_tags"] = ["AI match", "Source linked" if product.get("source_kind") == "live_web" else "Local development data"]
            ranked.append(product)
        ranked.sort(key=lambda item: (-item.get("match_score", 0), item.get("price") or 10**9))
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


def run_search(payload: dict[str, Any]) -> dict[str, Any]:
    brief, brief_event = BriefAgent().run(payload)
    raw_products, search_event, source_meta = SearchAgent().run(brief, payload.get("post_url"))
    products, evidence_event = ExtractionAgent().run(raw_products, source_meta)
    products, ranking_event = RankingAgent().run(products, brief)
    workflow = [brief_event, search_event, evidence_event, ranking_event]
    search_id = f"search-{uuid.uuid4().hex[:12]}"
    db.save_search(search_id, brief["raw_text"], brief, workflow)
    selected_products = _default_selection(products)
    total = sum(_money(product.get("price")) for product in selected_products)
    latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 5
    return {
        "search_id": search_id,
        "intent": brief,
        "products": products,
        "selected_product_ids": [product["id"] for product in selected_products],
        "summary": {"total": total, "item_count": len(selected_products), "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer"},
        "workflow": workflow,
        "source": source_meta,
    }


def _safe_plan_item(product: dict[str, Any]) -> dict[str, Any]:
    url = str(product.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        url = ""
    return {
        "id": str(product.get("id") or uuid.uuid4().hex),
        "name": str(product.get("name") or "Retailer product")[:180],
        "seller": str(product.get("seller") or "Retailer")[:100],
        "price": _money(product.get("price")),
        "delivery_label": str(product.get("delivery_label") or "Confirm at retailer")[:120],
        "url": url,
        "image": str(product.get("image") or IMAGE_PATH),
        "crop_index": _money(product.get("crop_index")),
        "source_kind": str(product.get("source_kind") or "source"),
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
        "total": sum(product["price"] for product in products),
        "items": products,
        "created_at": timestamp,
        "updated_at": timestamp,
        "notice": "Open each retailer link to complete checkout on that retailer's secure site. Artha never handles payment credentials.",
    }
    return db.save_purchase_plan(plan)
