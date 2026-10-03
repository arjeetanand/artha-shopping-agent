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
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .clients import AnakinClient, BriefModel, parse_price
from .catalog import FixtureCatalogClient
from .db import db, now_iso
from .location import LocationAgent
from .price_history import enrich_price_evidence, product_identity, valid_gtin, verified_price_offer
from .retailers import provider_status
from .settings import setting


MAX_REFERENCE_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_REFERENCE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _money(value: int | float | str | None) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return parse_price(str(value or "")) or 0


def _exact_direct_price(value: Any) -> tuple[int | None, str | None]:
    """Accept a single direct-page amount, never a range or starting price."""
    if isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        amount = _money(value)
        return (amount if amount > 0 else None), None
    if not isinstance(value, str):
        return None, None
    match = re.fullmatch(
        r"\s*(₹|rs\.?|inr)?\s*((?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:,\d{2})+,\d{3}|\d+)(?:\.\d{1,2})?)\s*(₹|rs\.?|inr)?\s*",
        value, flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    amount = _money(match.group(2).replace(",", ""))
    return (amount if amount > 0 else None), ("INR" if match.group(1) or match.group(3) else None)


def _date_label(days: int) -> str:
    target = date.today() + timedelta(days=max(days, 0))
    return target.strftime("%a")


def _parse_budget(text: str) -> int | None:
    cue = r"(?:₹|\b(?:under|below|budget|less than|upto|up to|spend|max(?:imum)?|rs\.?|inr)\b)"
    for match in re.finditer(rf"{cue}\D{{0,14}}([\d,]+)\s*(k|thousand|lakh|grand)?", text, flags=re.IGNORECASE):
        if re.match(r"\s*days?\b", text[match.end():], flags=re.IGNORECASE):
            continue
        amount = int(match.group(1).replace(",", ""))
        return amount * {"k": 1000, "thousand": 1000, "grand": 1000, "lakh": 100000}.get((match.group(2) or "").lower(), 1)
    match = re.search(r"\b([\d,]+)\s*(?:rupees|rs\.?|inr)\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))

    cue_match = re.search(cue, text, flags=re.IGNORECASE)
    if not cue_match and not re.fullmatch(r"\s*[a-z -]+\s+rupees?\s*", text, flags=re.IGNORECASE):
        return None
    words = re.findall(r"[a-z]+", text[cue_match.end():cue_match.end() + 55].lower() if cue_match else text[:55].lower())
    while words and words[0] in {"is", "of", "around", "about", "up", "to"}:
        words.pop(0)
    numbers = {**dict(zip("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(1, 20))),
               **dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))}
    total = current = 0
    scaled = False
    for word in words:
        if word in numbers:
            current += numbers[word]
        elif word == "hundred":
            current = max(current, 1) * 100
            scaled = True
        elif word in {"thousand", "lakh"}:
            total += max(current, 1) * (1000 if word == "thousand" else 100000)
            current = 0
            scaled = True
        elif word in {"rupee", "rupees"}:
            return total + current or None
        else:
            break
    return total + current if scaled else None


def _parse_days(text: str) -> int | None:
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
    }
    match = re.search(r"(?:within|in|before|by)\s*(\d{1,2}|[a-z]+)\s*days?\b", text, flags=re.IGNORECASE)
    if not match:
        match = re.fullmatch(r"\s*(\d{1,2}|[a-z]+)\s*days?\s*", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    return int(value) if value.isdigit() else number_words.get(value)


def _parse_pincode(text: str, payload: dict[str, Any] | None = None) -> str | None:
    for value in (
        (payload or {}).get("pincode"),
        (payload or {}).get("delivery_pincode"),
    ):
        candidate = re.sub(r"\D", "", str(value or ""))
        if re.fullmatch(r"\d{6}", candidate):
            return candidate
    match = re.search(r"(?:pin(?:code)?|postal\s*code)\s*[:#-]?\s*(\d{6})\b|\b(\d{6})\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def _parse_color(text: str) -> str | None:
    colors = (
        "black", "white", "red", "blue", "green", "yellow", "pink", "purple", "violet",
        "orange", "brown", "beige", "cream", "navy", "maroon", "grey", "gray", "gold",
        "silver", "pastel", "floral", "neutral", "multicolor", "multi-colour", "multicolor",
    )
    lowered = text.lower()
    explicit = re.search(r"(?:colou?r|shade)\s*(?:is|:|should be|in)?\s*([a-z-]+)", lowered)
    if explicit and explicit.group(1) in colors:
        return explicit.group(1)
    for color in colors:
        if re.search(rf"\b{re.escape(color)}\b", lowered):
            return color
    return None


def _parse_size(text: str) -> str | None:
    lowered = text.lower()
    if re.fullmatch(r"\s*(xxxl|xxl|xl|xs|small|medium|large|s|m|l)\s*", lowered):
        return lowered.strip()
    explicit = re.search(r"\bsize\s*[:=-]?\s*(xxxl|xxl|xl|xs|small|medium|large|s|m|l)\b", lowered)
    if explicit:
        return explicit.group(1)
    short_answer = re.search(r"(?:^|[\s,])((?:xxxl|xxl|xl|xs|small|medium|large|s|m|l))(?=$|[\s,])", lowered)
    if short_answer:
        return short_answer.group(1)
    for size in ("xxxl", "xxl", "xl", "medium", "large", "small", "xs"):
        if re.search(rf"\b{size}\b", lowered):
            return size
    return None


def _parse_fabric(text: str) -> str | None:
    fabrics = ("cotton", "linen", "silk", "chiffon", "georgette", "rayon", "viscose", "denim", "wool", "polyester")
    lowered = text.lower()
    return next((fabric for fabric in fabrics if re.search(rf"\b{fabric}\b", lowered)), None)


def _parse_occasion_or_style(text: str) -> str | None:
    values = (
        "casual", "party", "party wear", "office", "formal", "summer", "beach", "wedding",
        "ethnic", "western", "bodycon", "flowy", "maxi", "midi", "mini", "everyday",
    )
    lowered = text.lower()
    return next((value for value in values if re.search(rf"\b{re.escape(value)}\b", lowered)), None)


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


_PRODUCT_PATH = re.compile(r"/(?:products?|items?|dp|p|ip)/[^/?#]+", re.IGNORECASE)


def _requested_product_noun(brief: dict[str, Any]) -> str:
    category = str(brief.get("category") or "")
    words = re.findall(r"[a-z0-9]+", category.lower())
    generic = {"shopping", "product", "fashion", "clothing", "footwear", "electronics", "furniture", "appliances", "decor", "books", "outfit", "look", "wear", "wardrobe", "style", "attire"}
    if not words or words[-1] in generic:
        subject = re.split(r"\b(?:under|below|within|delivered?|arriv\w*|with|for|to|by|in|that|which|who)\b|\bI\s+(?:can|will|would|should|could)\b", str(brief.get("description") or brief.get("raw_text") or ""), maxsplit=1, flags=re.IGNORECASE)[0]
        words = re.findall(r"[a-z0-9]+", subject.lower())
    noun = words[-1] if words else ""
    if noun in generic | {"me", "a", "an", "the", "something", "item"} or re.search(r"\d", noun):
        return ""
    return noun[:-1] if noun.endswith("s") and not noun.endswith("ss") else noun


def _accessory_for_requested_product(brief: dict[str, Any], title: Any) -> bool:
    noun = _requested_product_noun(brief)
    if not noun:
        return False
    item = re.escape(noun) + r"s?"
    accessory = r"(?:covers?|cases?|protectors?|accessories|parts?|replacements?|mats?|pads?|cushions?|slipcovers?|sleeves?|straps?|stands?|holders?|chargers?|cables?|wheels?|armrests?)"
    text = str(title or "").lower()
    return bool(re.search(rf"\b{item}(?:\s+(?:seat|backrest|cushion|back|arm|base)){{0,2}}\s+{accessory}\b|\b{accessory}\b(?:\s+\w+){{0,3}}\s+for\s+(?:\w+\s+){{0,2}}{item}\b", text))


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


def _india_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _mission_input(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the additive mission object at the API boundary."""
    raw = payload.get("mission")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Mission must be an object")
    mission: dict[str, Any] = {}
    for field in ("occasion", "size", "color", "style"):
        value = str(raw.get(field) or "").strip()
        mission[field] = value[:120] or None
    budget = raw.get("budget")
    if budget not in (None, ""):
        mission["budget"] = _money(budget)
        if mission["budget"] <= 0:
            raise ValueError("Mission budget must be a positive amount")
    else:
        mission["budget"] = None
    pincode = re.sub(r"\D", "", str(raw.get("pincode") or ""))
    if raw.get("pincode") not in (None, "") and not re.fullmatch(r"\d{6}", pincode):
        raise ValueError("Mission pincode must be six digits")
    mission["pincode"] = pincode or None
    deadline = str(raw.get("arrive_by_date") or "").strip()
    if deadline:
        try:
            arrive_by_date = date.fromisoformat(deadline)
        except ValueError as error:
            raise ValueError("Mission arrival date must use YYYY-MM-DD") from error
        if arrive_by_date < _india_today():
            raise ValueError("Mission arrival date cannot be in the past")
        mission["arrive_by_date"] = arrive_by_date.isoformat()
    else:
        mission["arrive_by_date"] = None
    return mission


def _refresh_mission(brief: dict[str, Any], arrive_by_date: str | None = None) -> None:
    previous = brief.get("mission") if isinstance(brief.get("mission"), dict) else {}
    deadline = arrive_by_date if arrive_by_date is not None else previous.get("arrive_by_date")
    brief["mission"] = {
        "occasion": str(brief.get("occasion") or "").strip() or None,
        "arrive_by_date": deadline or None,
        "budget": _money(brief.get("budget")) or None,
        "pincode": str(brief.get("pincode") or "").strip() or None,
        "size": str(brief.get("size") or "").strip() or None,
        "color": str(brief.get("color") or "").strip() or None,
        "style": str(brief.get("style") or "").strip() or None,
    }


def _apply_mission(brief: dict[str, Any], payload: dict[str, Any], text: str) -> dict[str, Any]:
    mission = _mission_input(payload)
    if mission is None:
        _refresh_mission(brief)
        return brief
    for field in ("occasion", "budget", "pincode", "size", "color", "style"):
        if mission.get(field) is not None:
            brief[field] = mission[field]
    deadline = mission.get("arrive_by_date")
    if deadline:
        mission_deadline = date.fromisoformat(deadline)
        days = mission_deadline - _india_today()
        brief["arrive_by_days"] = days.days
        brief["arrive_by"] = f"by {mission_deadline.strftime('%d %b').lstrip('0')}"
    _refresh_mission(brief, deadline)
    brief["clarifications"] = _clarification_questions(
        text,
        brief,
        budget_explicit=mission.get("budget") is not None or _parse_budget(text) is not None,
        location_explicit=bool(_location_match(text) or payload.get("location") or payload.get("location_coordinates") or mission.get("pincode")),
        delivery_explicit=bool(deadline or _parse_days(text) is not None),
        pincode_explicit=bool(mission.get("pincode") or _parse_pincode(text, payload)),
    )
    return brief


def _clarification_questions(
    text: str,
    brief: dict[str, Any],
    *,
    budget_explicit: bool = False,
    location_explicit: bool = False,
    delivery_explicit: bool = False,
    pincode_explicit: bool = False,
) -> list[dict[str, str]]:
    """Return the smallest set of questions needed for a trustworthy search."""
    questions: list[dict[str, str]] = []
    if not budget_explicit and _parse_budget(text) is None:
        questions.append({"key": "budget", "question": "What is the maximum you would like to spend?"})
    if not location_explicit:
        questions.append({"key": "location", "question": "Where should this be delivered?"})
    if not delivery_explicit and _parse_days(text) is None:
        questions.append({"key": "delivery", "question": "When do you need it by?"})
    category = str(brief.get("category") or "").lower()
    is_fashion = any(token in category for token in ("fashion", "cloth", "dress", "shirt", "shoe", "outfit"))
    if is_fashion and not brief.get("color"):
        questions.append({"key": "color", "question": "Which color or color family should I look for?"})
    if is_fashion and not brief.get("size"):
        questions.append({"key": "size", "question": "What size should I check for?"})
    if is_fashion and location_explicit and not pincode_explicit:
        questions.append({"key": "pincode", "question": "What delivery pincode should I use to verify the delivery promise?"})
    return questions


def _location_match(text: str) -> re.Match[str] | None:
    """Find a city without mistaking `in three days` for a city name."""
    end = r"(?=\s+(?:within|for|with|under|before|by|and)\b|\s+in\s+(?:\d+|[a-z]+)\s+days?\b|[,.;]|$)"
    for pattern in (rf"(?:deliver(?:ed|y)?|ship(?:ped|ping)?)\s+(?:to|in)\s+([a-z][a-z .'-]{{2,40}}?){end}",
                    rf"\bin\s+([a-z][a-z .'-]{{2,40}}?){end}"):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidate = match.group(1).strip(" . ,\"'")
            if not candidate.lower().startswith(("a ", "the ", "my ")) and not (_parse_size(candidate) or _parse_color(candidate) or _parse_occasion_or_style(candidate)) and not re.fullmatch(r"(?:\d+|[a-z]+)\s+days?", candidate, flags=re.IGNORECASE):
                return match
    return None


def _rule_brief(
    payload: dict[str, Any],
    text: str,
    reference_image: dict[str, str] | None,
    image_name: str,
    *,
    extraction_source: str,
) -> dict[str, Any]:
    """Build a safe, deterministic brief when an LLM is unavailable or malformed."""
    lowered = text.lower()
    parsed_budget = _parse_budget(text)
    parsed_days = _parse_days(text)
    parsed_pincode = _parse_pincode(text, payload)
    parsed_color = _parse_color(text)
    parsed_size = _parse_size(text)
    parsed_fabric = _parse_fabric(text)
    parsed_style = _parse_occasion_or_style(text)
    budget = parsed_budget
    arrive_days = parsed_days
    quantity = _parse_quantity(text)
    brand = _parse_brand(text)
    if "chair" in lowered:
        category, occasion = "Office chair", "Office"
        must_have = _parse_specifications(text)
    elif any(word in lowered for word in ("shirt", "outfit", "dress", "shoe", "loafers", "saree", "kurta", "jeans", "trousers", "jacket")):
        category, occasion = "Clothing", "Everyday"
        must_have = _parse_specifications(text)
    else:
        category, occasion = "Shopping", "Everyday"
        must_have = _parse_specifications(text)
    location_match = _location_match(text)
    location = location_match.group(1).strip(" .,\"") if location_match else payload.get("location") or None
    if str(location).lower() == "bangalore":
        location = "Bengaluru"
    brief = {
        "category": category,
        "occasion": occasion,
        "budget": budget,
        "quantity": quantity,
        "brand": brand,
        "color": parsed_color,
        "size": parsed_size,
        "fabric": parsed_fabric,
        "pincode": parsed_pincode,
        "location": location,
        "arrive_by_days": arrive_days,
        "arrive_by": f"within {arrive_days} days" if arrive_days is not None else None,
        "must_have": must_have,
        "specifications": must_have,
        "nice_to_have": ["durable", "good value"],
        "style": parsed_style or ("cool" if re.search(r"\bcool\b", lowered) else "practical and considered"),
        "description": text or "Find a considered product",
        "raw_text": text or "Find a considered product",
        "image_name": image_name or None,
        "reference_image": {"name": image_name, "mime_type": reference_image["mime_type"]} if reference_image else None,
        "post_url": payload.get("post_url") or None,
        "extraction_source": extraction_source,
    }
    brief["clarifications"] = _clarification_questions(
        text,
        brief,
        budget_explicit=parsed_budget is not None,
        location_explicit=bool(location_match or payload.get("location") or payload.get("location_coordinates")),
        delivery_explicit=parsed_days is not None,
        pincode_explicit=bool(parsed_pincode),
    )
    return brief


class BriefAgent:
    name = "Brief agent"

    def __init__(self) -> None:
        self.model = BriefModel()

    def run(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        text = str(payload.get("text") or payload.get("query") or "").strip()
        reference_image = _reference_image(payload)
        image_name = str(reference_image["name"] if reference_image else payload.get("image_name") or "").strip()
        if setting("SHOPPINGHELP_SEARCH_MODE", "live").lower() in {"fixture", "sandbox", "mock"}:
            brief = _rule_brief(payload, text, reference_image, image_name, extraction_source="local fixture rules")
            brief = _apply_mission(brief, payload, text)
            return brief, {"agent": self.name, "status": "complete", "detail": "Local fixture rules extracted price, place, delivery, and must-haves"}
        llm_brief, provider = self.model.extract_brief(text, reference_image)
        provider_status = self.model.status()
        if not provider_status["configured"]:
            brief = _rule_brief(payload, text, reference_image, image_name, extraction_source=f"local rules fallback ({provider} unavailable)")
            brief = _apply_mission(brief, payload, text)
            return brief, {"agent": self.name, "status": "complete", "detail": f"{provider.title()} is unavailable; local rules fallback kept the brief usable"}
        if not llm_brief:
            brief = _rule_brief(payload, text, reference_image, image_name, extraction_source=f"local rules fallback ({provider} returned no usable JSON)")
            brief = _apply_mission(brief, payload, text)
            return brief, {"agent": self.name, "status": "complete", "detail": f"{provider.title()} returned no usable JSON; local rules fallback kept the brief usable"}
        explicit_budget = _parse_budget(text)
        explicit_days = _parse_days(text)
        explicit_location = _location_match(text)
        source = llm_brief or {}
        source_days = source.get("arrive_by_days")
        try:
            source_days = int(source_days) if source_days not in (None, "") else None
        except (TypeError, ValueError):
            source_days = None
        if explicit_days is None and source_days is not None and 0 <= source_days <= 90 and re.search(
            r"\b(?:next|by|before|within|on|arrive|delivered?)\b.{0,30}\b(?:today|tomorrow|weekend|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|days?|weeks?|\d{1,2})\b",
            text, flags=re.IGNORECASE,
        ):
            explicit_days = source_days
        source_quantity = _money(source.get("quantity"))
        source_category = _brief_text(source.get("category"))
        source_occasion = _brief_text(source.get("occasion"))
        source_style = _brief_text(source.get("style"))
        source_description = _brief_text(source.get("description"))
        source_brand = _brief_text(source.get("brand"))
        source_color = _brief_text(source.get("color")) or _parse_color(text)
        source_size = _brief_text(source.get("size")) or _parse_size(text)
        source_fabric = _brief_text(source.get("fabric")) or _parse_fabric(text)
        source_pincode = _parse_pincode(text, payload) or _parse_pincode(_brief_text(source.get("pincode")))
        source_specs = _brief_list(source.get("specifications"), [])
        source_must_have = _brief_list(source.get("must_have"), source_specs)
        brief = {
            "category": source_category or ("Fashion" if any(word in text.lower() for word in ["shirt", "pant", "shoe", "dress", "outfit", "look", "saree"]) else "Shopping"),
            "occasion": source_occasion or ("Office" if "office" in text.lower() else "Everyday"),
            "budget": explicit_budget,
            "quantity": max(1, min(source_quantity or _parse_quantity(text), 99)),
            "brand": source_brand or _parse_brand(text),
            "color": source_color or None,
            "size": source_size or None,
            "fabric": source_fabric or None,
            "pincode": source_pincode,
            "location": explicit_location.group(1).strip(" .,\"") if explicit_location else payload.get("location") or None,
            "arrive_by_days": explicit_days,
            "arrive_by": f"within {explicit_days} days" if explicit_days is not None else None,
            "must_have": source_must_have,
            "specifications": source_specs or source_must_have,
            "nice_to_have": _brief_list(source.get("nice_to_have"), ["durable", "easy to layer"]),
            "style": source_style or _parse_occasion_or_style(text) or ("cool" if re.search(r"\bcool\b", text, flags=re.IGNORECASE) else "quietly considered"),
            "description": source_description or text or "An office-ready neutral outfit",
            "raw_text": text or "Find a considered product",
            "image_name": image_name or None,
            "reference_image": {"name": image_name, "mime_type": reference_image["mime_type"]} if reference_image else None,
            "post_url": payload.get("post_url") or None,
            "extraction_source": provider if llm_brief else "local rules",
        }
        brief["clarifications"] = _clarification_questions(
            text,
            brief,
            budget_explicit=explicit_budget is not None,
            location_explicit=bool(explicit_location or payload.get("location") or payload.get("location_coordinates")),
            delivery_explicit=explicit_days is not None,
            pincode_explicit=bool(source_pincode),
        )
        if llm_brief and reference_image:
            detail = f"{provider.title()} analyzed the brief and reference image"
        elif llm_brief:
            detail = f"{provider.title()} extracted the brief"
        elif reference_image:
            detail = "Reference image attached; local rules extracted the typed brief"
        else:
            detail = "Local rules extracted price, place, and preferences"
        brief = _apply_mission(brief, payload, text)
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
                {
                    "mode": "sandbox",
                    "provider": "fixture_catalog",
                    "providers": provider_status(fixture_enabled=True),
                    "scrape": "not_requested",
                    "delivery_verification": "catalog_fixture",
                    "delivery_pincode": brief.get("pincode"),
                },
            )
        if not self.anakin.configured:
            raise RuntimeError("Anakin live extraction is not configured. Add ANAKIN_API_KEY and restart the API.")
        source_context = ""
        scrape_status = "not_requested"
        if post_url:
            try:
                scraped = self.anakin.scrape_inline(post_url)
                details = scraped.get("generatedJson") or {}
                if isinstance(details, dict) and isinstance(details.get("data"), dict):
                    details = details["data"]
                identity = str(details.get("name") or details.get("productName") or details.get("title") or "") if isinstance(details, dict) else ""
                source_context = (identity or str(scraped.get("title") or scraped.get("pageTitle") or scraped.get("markdown") or scraped.get("content") or ""))[:900]
                scrape_status = "complete" if source_context else "empty"
            except Exception:
                # A single source page should not prevent the user from receiving
                # a live cross-store search. The UI records that the page itself
                # could not be used as evidence.
                scrape_status = "unavailable"
        category = str(brief.get("category") or "product")
        subject = str(brief.get("description") or category)[:120]
        product_noun = _requested_product_noun(brief)
        terms = " ".join(str(brief.get(field) or "") for field in ("brand", "color", "size", "fabric"))
        must_have = " ".join(str(value) for value in (brief.get("must_have") or [])[:2])
        budget = f"under ₹{brief['budget']}" if brief.get("budget") else ""
        base = " ".join(part for part in (category, subject, terms, must_have, source_context[:100], budget, "buy online India") if part)
        queries = (f"{base} individual product page price", f"{base} site:flipkart.com", f"{base} site:amazon.in")
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        retrieved = successful = 0
        last_error: Exception | None = None
        for query in queries:
            try:
                response = self.anakin.search(query, num_results=10)
            except Exception as error:
                last_error = error
                continue
            successful += 1
            data = response.get("data") if isinstance(response, dict) else None
            results = response.get("results") or (data.get("results") if isinstance(data, dict) else []) or []
            if not isinstance(results, list):
                continue
            retrieved += len(results)
            for raw in results:
                if not isinstance(raw, dict):
                    continue
                try:
                    url = _reference_url(raw.get("url") or raw.get("link"))
                except ValueError:
                    continue
                host = (urlparse(url).hostname or "") if url else ""
                if any(term in host for term in ("camelcamelcamel", "review", "compare", "pricehistory", "pricetracker")):
                    continue
                details = raw.get("generatedJson") or raw.get("data") or {}
                if isinstance(details, dict) and isinstance(details.get("data"), dict):
                    details = details["data"]
                page_type = re.sub(r"[^a-z]", "", str(details.get("pageType") or "").lower()) if isinstance(details, dict) else ""
                if page_type and page_type not in {"product", "productdetail", "productpage", "pdp"}:
                    continue
                title = str(details.get("name") or details.get("title") or "") if isinstance(details, dict) else ""
                title = title or str(raw.get("title") or raw.get("name") or "")
                if _accessory_for_requested_product(brief, title):
                    continue
                if product_noun and not re.search(rf"\b{re.escape(product_noun)}s?\b", title, flags=re.IGNORECASE):
                    continue
                if url and url not in seen_urls and (page_type or _PRODUCT_PATH.search(urlparse(url).path)):
                    candidates.append(raw)
                    seen_urls.add(url)
        if not successful and last_error:
            raise RuntimeError("Anakin live search failed. Check ANAKIN_API_KEY and network access.") from last_error
        by_host: dict[str, list[dict[str, Any]]] = {}
        for raw in candidates:
            host = urlparse(str(raw.get("url") or raw.get("link"))).hostname or ""
            by_host.setdefault(host, []).append(raw)
        sources = ([items[0] for items in by_host.values()] + [raw for items in by_host.values() for raw in items[1:]])[:10]
        detail = f"Found {len(sources)} individual product-page candidates across {successful} searches; skipped {retrieved - len(candidates)} listing or article links"
        if not sources:
            detail = f"No individual product page found across {successful} searches; {retrieved} listing or article links were excluded"
        return sources, {"agent": self.name, "status": "complete" if sources else "waiting", "detail": detail}, {
            "mode": "live",
            "scrape": scrape_status,
            "providers": provider_status(live_configured=True),
            "delivery_verification": "source_reported_only",
            "delivery_pincode": brief.get("pincode"),
            "search": {"queries": successful, "retrieved": retrieved, "product_candidates": len(sources)},
        }


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
        price = max(0, _money(raw_price))
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
            "currency": str(data.get("currency")).strip().upper() if isinstance(data, dict) and data.get("currency") else None,
            "shipping_cost": shipping_cost,
            "total_price": price + shipping_cost,
            "rating": data.get("rating") if isinstance(data, dict) else 0,
            "delivery_days": delivery_days,
            "delivery_label": str(data.get("delivery_label") if isinstance(data, dict) and data.get("delivery_label") else "Confirm at retailer"),
            "stock": data.get("stock") if isinstance(data, dict) else None,
            "features": data.get("features") if isinstance(data, dict) and isinstance(data.get("features"), list) else [],
            "colors": data.get("colors") if isinstance(data, dict) and isinstance(data.get("colors"), list) else [],
            "sizes": data.get("sizes") if isinstance(data, dict) and isinstance(data.get("sizes"), list) else [],
            "variants": data.get("variants") if isinstance(data, dict) and isinstance(data.get("variants"), list) else [],
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
            if source_meta.get("mode") == "live":
                return [], {"agent": self.name, "status": "waiting", "detail": "No individual retailer product page was available for evidence extraction"}
            raise RuntimeError("The local catalog returned no usable products for this brief.")
        detail = "Normalized local catalog fields and constraint evidence" if source_meta.get("mode") == "sandbox" else "Normalized live source fields and retailer evidence"
        return products[:10], {"agent": self.name, "status": "complete", "detail": detail}


class AnalysisAgent:
    """Derive transparent review and price signals without filling unknowns."""

    name = "Analysis agent"

    @staticmethod
    def _review_signal(product: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
        sources = [source for source in (product.get("review_sources") or []) if isinstance(source, dict)]
        if product.get("source_kind") == "sandbox_catalog":
            existing = product.get("review_reliability")
            try:
                reliability = float(existing) if existing is not None else None
            except (TypeError, ValueError):
                reliability = None
            return reliability, product.get("review_analysis") if isinstance(product.get("review_analysis"), dict) else {}

        sample_count = sum(_money(source.get("count")) for source in sources)
        if not sources:
            return None, {
                "label": "No review sources",
                "detail": "No review-source metadata was returned, so review quality could not be assessed.",
            }
        return None, {
            "label": f"{len(sources)} source{'s' if len(sources) != 1 else ''} listed",
            "detail": f"Source metadata lists {sample_count or 'an unknown number of'} reviews; counts and ratings do not verify reviewer identity or authenticity.",
        }

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
        review_metadata = 0
        price_known = 0
        for product in products:
            reliability, review_analysis = self._review_signal(product)
            if product.get("review_sources"):
                review_metadata += 1
            if reliability is not None:
                product["review_reliability"] = reliability
            else:
                product["review_reliability"] = None
            if review_analysis:
                product["review_analysis"] = review_analysis
            price_history = self._price_signal(product)
            if price_history:
                product["price_history"] = price_history
                price_known += 1
        return products, {
            "agent": self.name,
            "status": "complete",
            "detail": f"Logged review-source metadata for {review_metadata} products and checked price history for {price_known}; review authenticity remains unverified",
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
    def _page_gtin(html: Any, page_title: str) -> str | None:
        """Read only the verified product's GTIN from retailer page JSON-LD."""
        if not isinstance(html, str) or not html:
            return None

        class JsonLdScripts(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.scripts: list[str] = []
                self.parts: list[str] | None = None

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                if tag == "script" and any(key == "type" and str(value or "").lower().split(";")[0].strip() == "application/ld+json" for key, value in attrs):
                    self.parts = []

            def handle_data(self, data: str) -> None:
                if self.parts is not None:
                    self.parts.append(data)

            def handle_endtag(self, tag: str) -> None:
                if tag == "script" and self.parts is not None:
                    self.scripts.append("".join(self.parts))
                    self.parts = None

        parser = JsonLdScripts()
        try:
            parser.feed(html)
        except Exception:
            return None
        wanted = re.sub(r"[^\w]+", " ", page_title.casefold()).strip()
        found: set[str] = set()

        def collect(node: Any, schema_context: bool = False) -> None:
            if isinstance(node, list):
                for item in node:
                    collect(item, schema_context)
            elif isinstance(node, dict):
                schema_context = schema_context or "schema.org" in str(node.get("@context") or "")
                types = node.get("@type")
                types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
                name = re.sub(r"[^\w]+", " ", str(node.get("name") or "").casefold()).strip()
                if schema_context and name == wanted and any(str(kind).rsplit("/", 1)[-1] == "Product" for kind in types):
                    found.update(filter(None, (valid_gtin(node.get(field)) for field in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"))))
                for field in ("@graph", "mainEntity"):
                    collect(node.get(field), schema_context)

        for script in parser.scripts:
            try:
                collect(json.loads(script))
            except (TypeError, ValueError):
                continue
        return next(iter(found)) if len(found) == 1 else None

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
        try:
            url = _reference_url(enriched.get("url"))
        except ValueError:
            url = None
        if not url:
            enriched["research_status"] = "waiting"
            enriched["research_sources"] = [{"name": "Product URL", "status": "missing", "detail": "No public product page was returned"}]
            return enriched, False
        enriched["url"] = url
        host = self._host(url)
        try:
            scraped = self.anakin.scrape_inline(url)
        except Exception:
            enriched["research_status"] = "waiting"
            enriched["research_sources"] = [{"name": host, "status": "unavailable", "detail": "Direct page research could not be completed"}]
            return enriched, False

        scraped_data = _scraped_mapping(scraped)
        scraped_text = _scraped_text(scraped)
        page_title = str(scraped_data.get("name") or scraped_data.get("title") or "").strip()
        result_tokens = re.findall(r"[a-z0-9]+", str(enriched.get("name") or "").lower())
        page_tokens = re.findall(r"[a-z0-9]+", page_title.lower())
        page_type = re.sub(r"[^a-z]", "", str(scraped_data.get("pageType") or "").lower())
        product_page = not page_type or page_type in {"product", "productdetail", "productpage", "pdp"}
        leading_title = re.split(r"\s+[|–—]\s+", str(enriched.get("name") or ""), maxsplit=1)[0]
        leading_tokens = re.findall(r"[a-z0-9]+", leading_title.lower())
        title_match = result_tokens == page_tokens or (page_type and leading_tokens == page_tokens)
        if not title_match and product_page and page_type and len(page_tokens) >= 4:
            title_match = any(result_tokens[index:index + len(page_tokens)] == page_tokens for index in range(len(result_tokens) - len(page_tokens) + 1))
        product_fields = {"price", "stock", "delivery_days", "features", "variants"}
        if not isinstance(scraped, dict) or not page_title or not result_tokens or not product_page or not title_match or not product_fields.intersection(scraped_data):
            enriched["research_status"] = "waiting"
            enriched["research_sources"] = [{"name": host, "status": "unverified", "detail": "The direct page did not confirm this exact product and its purchase details"}]
            return enriched, False

        data = scraped_data
        text = scraped_text
        evidence = [str(item) for item in (enriched.get("evidence") or []) if str(item).strip()]
        fields: list[str] = []
        enriched["name"] = page_title[:180]
        gtin = self._page_gtin(scraped.get("html"), page_title)
        if gtin:
            enriched["gtin"] = gtin
            enriched["gtin_source"] = "direct_product_jsonld"
            fields.append("GTIN")
        for field in ("brand", "seller"):
            value = data.get(field)
            if isinstance(value, dict):
                value = value.get("name")
            enriched[field] = str(value).strip()[:120] if isinstance(value, str) and value.strip() else (host if field == "seller" else None)
            if enriched[field] is not None:
                fields.append(field)
        reliability = data.get("seller_reliability")
        enriched["seller_reliability"] = reliability if isinstance(reliability, (int, float)) and not isinstance(reliability, bool) and 0 <= reliability <= 1 else None
        if enriched["seller_reliability"] is not None:
            fields.append("seller_reliability")
        try:
            direct_rating = float(data.get("rating"))
            enriched["rating"] = direct_rating if 0 <= direct_rating <= 5 else None
        except (TypeError, ValueError):
            enriched["rating"] = None
        if enriched["rating"] is not None:
            fields.append("rating")
        for field in ("image",):
            value = data.get(field)
            if value in (None, "", [], {}):
                continue
            if enriched.get(field) in (None, "", [], {}):
                enriched[field] = value
                fields.append(field)
        direct_days = data.get("delivery_days")
        try:
            direct_days = int(direct_days) if direct_days not in (None, "") else None
            if direct_days is not None and not 0 <= direct_days <= 365:
                direct_days = None
        except (TypeError, ValueError):
            direct_days = None
        enriched["delivery_days"] = direct_days
        enriched["delivery_label"] = str(data.get("delivery_label") or "")[:120] if direct_days is not None else None
        enriched["stock"] = data.get("stock") if data.get("stock") not in (None, "") else None
        fields.extend(field for field in ("delivery_days", "stock") if enriched[field] is not None)
        enriched["fabric"] = str(data.get("fabric") or data.get("material") or "")[:120] or None
        for field in ("features", "variants", "colors", "sizes"):
            value = data.get(field)
            enriched[field] = value if isinstance(value, list) else []
            if enriched[field]:
                fields.append(field)
        shipping = data.get("shipping_cost")
        enriched["shipping_verified"] = (isinstance(shipping, (int, float)) and not isinstance(shipping, bool) and shipping >= 0) or (
            isinstance(shipping, str) and bool(re.fullmatch(r"\s*(?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d{1,2})?\s*", shipping, flags=re.IGNORECASE))
        )
        enriched["shipping_cost"] = max(0, _money(shipping)) if enriched["shipping_verified"] else None
        scraped_price, price_currency = _exact_direct_price(data.get("price"))
        direct_currency = str(data.get("currency") or "").strip().upper()
        direct_currency = "INR" if direct_currency in {"RS", "RS.", "₹"} else direct_currency or None
        enriched["currency"] = None if price_currency and direct_currency and price_currency != direct_currency else direct_currency or price_currency

        current_price = _money(enriched.get("price"))
        enriched["price_verification"] = None
        enriched.pop("direct_page_price", None)
        if scraped_price:
            enriched["direct_page_price"] = scraped_price
        if scraped_price and current_price and scraped_price != current_price:
            enriched["price"] = scraped_price
            enriched["price_verification"] = "mismatch"
            evidence.append(f"Search price {current_price} differs from direct page price {scraped_price}; showing the direct price, confirm at checkout")
            fields.append("price")
        elif scraped_price and not current_price:
            enriched["price"] = scraped_price
            enriched["price_verification"] = "direct"
            fields.append("price")
        elif scraped_price:
            enriched["price_verification"] = "matched"
        if scraped_price:
            enriched["total_price"] = scraped_price + _money(enriched.get("shipping_cost"))
            if enriched["currency"] is None:
                enriched["price_verification"] = "currency_unknown"

        for field in ("review_sources", "price_history"):
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

        # URL shape only prioritizes checks; _one still verifies the exact product.
        public_entries = []
        for index, product in enumerate(products):
            try:
                if _reference_url(product.get("url")):
                    public_entries.append((index, product))
            except ValueError:
                continue
        candidate_entries = sorted(
            public_entries,
            key=lambda entry: not bool(_PRODUCT_PATH.search(urlparse(str(entry[1]["url"])).path)),
        )[:6]
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
                    product, ok = copy.deepcopy(enriched[index]), False
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
        max_days = max(0, _money(brief.get("arrive_by_days"))) if brief.get("arrive_by_days") is not None else 5
        quantity = max(1, min(_money(brief.get("quantity")) or 1, 99))
        requested_brand = str(brief.get("brand") or "").strip().lower()
        requested_color = str(brief.get("color") or "").strip().lower()
        requested_size = str(brief.get("size") or "").strip().lower()
        requested_fabric = str(brief.get("fabric") or "").strip().lower()
        size_aliases = {"small": "s", "medium": "m", "large": "l", "extra large": "xl"}

        def size_key(value: Any) -> str:
            value = str(value or "").strip().lower()
            return size_aliases.get(value, value)

        def stock_quantity(value: Any) -> int | None:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 10**9 and int(value) == value:
                return int(value)
            if isinstance(value, str):
                match = re.fullmatch(r"\s*(\d{1,9})(?:\s+(?:in stock|available))?\s*", value, flags=re.IGNORECASE)
                return int(match.group(1)) if match else None
            return None

        ranked: list[dict[str, Any]] = []
        for product in products:
            features = " ".join(str(value) for value in (product.get("features") or [])).lower()
            product_text = " ".join((str(product.get("name") or ""), str(product.get("description") or ""), features)).lower()
            must_have = [str(item).lower() for item in (brief.get("must_have") or [])]
            live = product.get("source_kind") == "live_web"
            positive_features = " ".join(
                str(value) for value in (product.get("features") or [])
                if not re.search(r"\b(?:no|not|without|non|faux|imitation|look|style)\b", str(value), flags=re.IGNORECASE)
            ).lower()
            feature_evidence = positive_features if live and product.get("research_status") == "complete" else "" if live else product_text
            matched_features = [item for item in must_have if item in feature_evidence or item in _parse_specifications(feature_evidence)]
            feature_score = len(matched_features) / max(len(must_have), 1)
            shipping_cost = _money(product.get("shipping_cost"))
            product["shipping_cost"] = shipping_cost
            product["quantity"] = quantity
            delivery = product.get("delivery_days")
            delivery_score = 0.35 if delivery is None else max(0, min(1, 1 - max(delivery - max_days, 0) / max(max_days, 1)))
            deal_score = product.get("price_history", {}).get("deal_score") if isinstance(product.get("price_history"), dict) else None
            deal_bonus = max(0, min(5, round(float(deal_score or 0) * 5)))
            brand_text = " ".join(str(product.get(field) or "") for field in ("brand", "seller", "name")).lower()
            brand_fit = True if not requested_brand else requested_brand in brand_text
            variants = [value for value in (product.get("variants") or []) if isinstance(value, dict)]
            available_colors = [str(value).lower() for value in (product.get("colors") or []) if str(value).strip()] or [str(value.get("color")).lower() for value in variants if value.get("color")]
            available_sizes = [str(value).lower() for value in (product.get("sizes") or []) if str(value).strip()] or [str(value.get("size")).lower() for value in variants if value.get("size")]
            color_fit = None if not requested_color or not available_colors else any(requested_color in value for value in available_colors)
            size_fit = None if not requested_size or not available_sizes else size_key(requested_size) in {size_key(value) for value in available_sizes}
            variant_fit = None
            matching_variants: list[dict[str, Any]] = []
            if variants and (requested_color or requested_size):
                comparable = [value for value in variants if (not requested_color or value.get("color")) and (not requested_size or value.get("size"))]
                if comparable:
                    matches = [value for value in comparable if (not requested_color or requested_color in str(value.get("color")).lower()) and (not requested_size or size_key(value.get("size")) == size_key(requested_size))]
                    if not matches:
                        variant_fit = False
                    else:
                        checked = [(value, stock_quantity(value.get("stock"))) for value in matches]
                        matching_variants = [value for value, stock in checked if value.get("available") is True and (stock >= quantity if stock is not None else value.get("stock") is None and quantity == 1)]
                        if matching_variants:
                            variant_fit = True
                        elif all(value.get("available") is False or (stock is not None and stock < quantity) for value, stock in checked):
                            variant_fit = False
            variant_prices = []
            for value in matching_variants:
                raw_price = value.get("price")
                if (isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool) and 0 < raw_price < 10**9) or (
                    isinstance(raw_price, str) and re.fullmatch(r"\s*(?:₹|rs\.?|inr)?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*", raw_price, flags=re.IGNORECASE)
                ):
                    variant_prices.append(_money(raw_price))
            variant_price = max(variant_prices) if variant_prices and len(variant_prices) == len(matching_variants) else None
            variant_price_unknown = live and variant_fit is True and (variant_price is None or len(matching_variants) != 1)
            if variant_price_unknown:
                product["price_verification"] = "variant_unverified"
            elif product.get("price_verification") == "variant_unverified" and product.get("direct_page_price"):
                product["price_verification"] = "direct"
            if live and variant_fit is True and len(matching_variants) == 1 and variant_price and product.get("research_status") == "complete":
                product["direct_page_price"] = variant_price
                if product.get("price_verification") in {None, "matched", "direct"}:
                    product["price_verification"] = "direct"
                for field in ("color", "size"):
                    if matching_variants[0].get(field):
                        product[field] = matching_variants[0][field]
            price = variant_price or _money(product.get("direct_page_price")) or _money(product.get("price"))
            if variant_price or (live and product.get("direct_page_price")):
                product["price"] = price
                total_price = price + shipping_cost
            else:
                total_price = _money(product.get("total_price")) or price + shipping_cost
            product["total_price"] = total_price or None
            product["unit_total"] = total_price or None
            product["line_total"] = total_price * quantity if total_price else None
            line_total = product["line_total"]
            budget_score = max(0, min(1, 1 - max(line_total - budget, 0) / budget)) if line_total and not variant_price_unknown else 0.35
            stock_count = stock_quantity(product.get("stock"))
            stock_fit = stock_count >= quantity if stock_count is not None else None
            brand_bonus = 8 if brand_fit and requested_brand else -8 if requested_brand else 0
            stock_bonus = 4 if stock_fit is True else -8 if stock_fit is False else 0
            match_score = round(55 + feature_score * 20 + budget_score * 15 + delivery_score * 10 + deal_bonus + brand_bonus + stock_bonus)
            product["match_score"] = min(99, max(42, match_score))
            product["budget_fit"] = line_total <= budget if line_total and not variant_price_unknown else None
            product["delivery_fit"] = delivery <= max_days if delivery is not None else None
            product["brand_fit"] = brand_fit if requested_brand else None
            product["stock_fit"] = stock_fit
            product["variant_fit"] = variant_fit
            if requested_fabric and live:
                material = re.sub(r"[^a-z0-9]+", " ", str(product.get("fabric") or "").lower()).strip()
                pure_material = material in {requested_fabric, f"100 {requested_fabric}"}
                known_other = material and requested_fabric not in material.split() and _parse_fabric(material) is not None
                product["fabric_fit"] = True if pure_material else False if known_other else None
            else:
                product["fabric_fit"] = True if requested_fabric and requested_fabric in product_text else None
            product["must_have_fit"] = True if must_have and len(matched_features) == len(must_have) else None
            currency = str(product.get("currency") or "").upper()
            product["currency_fit"] = currency in {"INR", "₹"} if currency else None
            product["category_fit"] = not _accessory_for_requested_product(brief, product.get("name"))
            product["delivery_label"] = product.get("delivery_label") or (f"Arrives {_date_label(delivery)}" if delivery else "Confirm at retailer")
            product["reason_tags"] = [
                "Within budget" if product["budget_fit"] is True else "Over budget" if product["budget_fit"] is False else "Price needs confirmation",
                "Within delivery window" if product["delivery_fit"] is True else "Misses delivery window" if product["delivery_fit"] is False else "Delivery needs confirmation",
                f"{quantity} in stock" if stock_fit is True and quantity > 1 else "Stock covers quantity" if stock_fit is True else f"Only {stock_count} in stock" if stock_fit is False else "Availability needs confirmation",
                "Seller name listed; verify at retailer" if product.get("seller") else "Seller identity needs confirmation",
            ]
            if requested_brand:
                product["reason_tags"].append("Preferred brand" if brand_fit else "Brand preference not met")
            if requested_color:
                product["reason_tags"].append("Color available" if color_fit is True else "Color not available" if color_fit is False else "Color needs confirmation")
            if requested_size:
                product["reason_tags"].append("Size available" if size_fit is True else "Size not available" if size_fit is False else "Size needs confirmation")
            if variant_fit is False:
                product["reason_tags"].append("Requested color and size combination unavailable")
            elif variant_fit is None and requested_color and requested_size:
                product["reason_tags"].append("Color and size combination needs confirmation")
            if requested_fabric:
                product["reason_tags"].append("Fabric matches" if product["fabric_fit"] is True else "Fabric differs from request" if product["fabric_fit"] is False else "Fabric needs confirmation")
            if not product["category_fit"]:
                product["reason_tags"].append("Accessory, not the requested product")
            product["color_fit"] = color_fit
            product["size_fit"] = size_fit
            product["eligible"] = (
                product["currency_fit"] is not False
                and product["category_fit"]
                and variant_fit is not False
                and
                product["budget_fit"] is not False
                and product["delivery_fit"] is not False
                and product["stock_fit"] is not False
                and color_fit is not False
                and size_fit is not False
                and product["fabric_fit"] is not False
            )
            ranked.append(product)
        if "lower total cost" in (brief.get("nice_to_have") or []):
            ranked.sort(key=lambda item: (not item.get("eligible", True), item.get("line_total") or 10**9, -item.get("match_score", 0)))
        else:
            ranked.sort(key=lambda item: (not item.get("eligible", True), -item.get("match_score", 0), item.get("line_total") or 10**9))
        return ranked, {"agent": self.name, "status": "complete", "detail": "Ranked by fit, budget, delivery, and source evidence"}


def _default_selection(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [
        product
        for product in products
        if product.get("eligible") is not False
        and product.get("budget_fit") is not False
        and product.get("delivery_fit") is not False
    ]
    # Never auto-select a product with a known budget, delivery, stock, color,
    # or size failure. The cards can still be shown for transparency, but the
    # shopper must explicitly choose a trade-off.
    candidates = [product for product in eligible if _money(product.get("price")) > 0] or eligible
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


def _mission_decision(products: list[dict[str, Any]], brief: dict[str, Any]) -> dict[str, Any]:
    """Turn the existing ranked list into one accountable, evidence-gated action."""
    candidates = [product for product in products if product.get("eligible") is not False]
    if not candidates:
        failed = [product for product in products if isinstance(product, dict)]
        risks = []
        changes = {
            "budget_fit": "raise the budget",
            "delivery_fit": "move the arrival date later",
            "stock_fit": "choose a size or style with wider stock",
            "variant_fit": "choose another color or size combination",
            "size_fit": "relax the size requirement",
            "color_fit": "relax the colour requirement",
            "fabric_fit": "choose a different fabric",
            "currency_fit": "choose an INR-priced retailer source",
            "category_fit": "search for the requested product instead of an accessory",
        }
        next_step = "Relax the style or occasion requirement."
        if failed:
            closest = min(failed, key=lambda product: (sum(product.get(field) is False for field in changes), -(product.get("match_score") or 0)))
            needed = [field for field in changes if closest.get(field) is False]
            if "variant_fit" in needed:
                needed = [field for field in needed if field not in {"size_fit", "color_fit"}]
            if needed:
                phrases = [changes[field] for field in needed]
                next_step = (" and ".join(phrases) if len(phrases) < 3 else f"{', '.join(phrases[:-1])} and {phrases[-1]}").capitalize() + "."
        for field, label in (
            ("budget_fit", "Budget"),
            ("delivery_fit", "Arrival deadline"),
            ("stock_fit", "Stock"),
            ("variant_fit", "Requested variant"),
            ("color_fit", "Colour"),
            ("size_fit", "Size"),
            ("fabric_fit", "Fabric"),
            ("currency_fit", "Currency"),
            ("category_fit", "Product type"),
        ):
            if any(product.get(field) is False for product in failed):
                risks.append(f"{label} does not clear the mission")
        return {
            "status": "no_safe_fit",
            "recommended_product_id": None,
            "fallback_product_id": None,
            "reasons": ["No retailer source clears every hard constraint."],
            "blocking_risks": risks or ["No eligible retailer source was returned."],
            "mission_change": next_step,
            "checked_at": now_iso(),
        }

    def purchase_risks(candidate: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        if candidate.get("research_status") != "complete":
            risks.append("Exact product page needs confirmation")
        if candidate.get("source_kind") == "live_web" and candidate.get("price_verification") not in {"matched", "direct"}:
            risks.append("Price needs direct retailer confirmation")
        if candidate.get("source_kind") == "live_web" and candidate.get("shipping_verified") is not True:
            risks.append("Shipping and final total need retailer confirmation")
        if candidate.get("currency_fit") is not True:
            risks.append("Currency needs retailer confirmation")
        if urlparse(str(candidate.get("url") or "")).scheme not in {"http", "https"}:
            risks.append("Retailer link needs confirmation")
        if _money(candidate.get("line_total") or candidate.get("total_price") or candidate.get("price")) <= 0:
            risks.append("Price needs retailer confirmation")
        if str(candidate.get("price_verification") or "").lower() in {"mismatch", "conflict", "conflicting"}:
            risks.append("Search and retailer prices do not match")
        for field, label in (("delivery_fit", "Delivery date"), ("stock_fit", "Stock")):
            if candidate.get(field) is not True:
                risks.append(f"{label} needs retailer confirmation")
        if brief.get("color") and candidate.get("color_fit") is not True:
            risks.append("Colour needs retailer confirmation")
        if brief.get("size") and candidate.get("size_fit") is not True:
            risks.append("Size needs retailer confirmation")
        if (brief.get("color") or brief.get("size")) and candidate.get("variant_fit") is not True:
            risks.append("Requested variant availability needs retailer confirmation")
        if brief.get("fabric") and candidate.get("fabric_fit") is not True:
            risks.append("Fabric needs retailer confirmation")
        if brief.get("must_have") and candidate.get("must_have_fit") is not True:
            risks.append("Required features need retailer confirmation")
        return risks

    product = next((candidate for candidate in candidates if not purchase_risks(candidate)), candidates[0])
    risks = purchase_risks(product)
    fallback = next((candidate for candidate in candidates if candidate is not product), None)
    reasons = [
        label
        for field, label in (
            ("budget_fit", "Within budget"),
            ("delivery_fit", "Meets the arrival deadline"),
            ("stock_fit", "Stock is confirmed"),
            ("color_fit", "Colour is confirmed"),
            ("size_fit", "Size is confirmed"),
            ("variant_fit", "Requested variant is confirmed"),
            ("fabric_fit", "Fabric is confirmed"),
            ("must_have_fit", "Required features are confirmed"),
        )
        if product.get(field) is True
    ]
    return {
        "status": "buy_now" if not risks else "verify_before_buy",
        "recommended_product_id": str(product.get("id") or "") or None,
        "fallback_product_id": (str(fallback.get("id") or "") or None) if fallback else None,
        "reasons": reasons or ["Highest-ranked source with no known hard constraint failure."],
        "blocking_risks": risks,
        "mission_change": None,
        "checked_at": now_iso(),
    }


def _decision_selection(products: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    recommended_id = decision.get("recommended_product_id")
    return [product for product in products if product.get("id") == recommended_id][:1]


def _targeted_cross_store_offers(products: list[dict[str, Any]], brief: dict[str, Any], source_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Check a few other retailer pages for the provisionally recommended item."""
    report: dict[str, Any] = {"status": "skipped", "attempted": 0, "matched": 0}
    source_meta["cross_store"] = report
    if source_meta.get("mode") != "live" or not products:
        return []

    preview = copy.deepcopy(products)
    for product in preview:
        product["price_history"] = {}  # Search snippets cannot rank a product as a historical deal.
    preview, _ = RankingAgent().run(preview, brief)
    decision = _mission_decision(preview, brief)
    target = next((product for product in preview if product.get("id") == decision.get("recommended_product_id")), None)
    if not target:
        return []
    key, basis = product_identity(target)
    report["identity_basis"] = basis
    if basis not in {"gtin", "brand_and_exact_title"} or not verified_price_offer(target, key, now_iso()):
        return []

    def host(url: str) -> str:
        return (urlparse(url).hostname or "").removeprefix("www.")

    checked_hosts = {
        host(str(product.get("url") or "")) for product in products
        if product_identity(product)[0] == key and verified_price_offer(product, key, now_iso())
    }
    if len(checked_hosts) > 1:
        report["status"] = "already_compared"
        return []

    name = re.sub(r"[^\w .+\-]", " ", str(target.get("name") or ""))[:120].strip()
    brand = re.sub(r"[^\w .+\-]", " ", str(target.get("brand") or ""))[:60].strip()
    identifier = f"GTIN {target['gtin']}" if basis == "gtin" else f"{brand} {name} colour {target.get('color') or ''} size {target.get('size') or ''}"
    query = f"Find other Indian retailer product detail pages for the exact {name} by {brand}, {identifier}. Return purchase pages for this same item, not articles or category pages."
    report["status"] = "searching"
    try:
        response = AnakinClient().search(query, num_results=10)
        data = response.get("data") if isinstance(response, dict) else None
        results = response.get("results") or (data.get("results") if isinstance(data, dict) else []) or []
        if not isinstance(results, list):
            results = []
        checked_urls = {str(product.get("url") or "").rstrip("/") for product in products if product.get("research_status") in {"complete", "waiting"}}
        candidates: list[dict[str, Any]] = []
        candidate_hosts: set[str] = set()
        for raw in results:
            if not isinstance(raw, dict):
                continue
            try:
                url = _reference_url(raw.get("url") or raw.get("link"))
            except ValueError:
                continue
            if not url or url.rstrip("/") in checked_urls or host(url) in checked_hosts | candidate_hosts:
                continue
            details = raw.get("generatedJson") or raw.get("data") or {}
            if isinstance(details, dict) and isinstance(details.get("data"), dict):
                details = details["data"]
            page_type = re.sub(r"[^a-z]", "", str(details.get("pageType") or "").lower()) if isinstance(details, dict) else ""
            if page_type not in {"product", "productdetail", "productpage", "pdp"} and not _PRODUCT_PATH.search(urlparse(url).path):
                continue
            candidates.append({**raw, "url": url})
            checked_urls.add(url.rstrip("/"))
            candidate_hosts.add(host(url))
            if len(candidates) == 4:
                break
        report["attempted"] = len(candidates)
        if not candidates:
            report["status"] = "no_candidates"
            return []
        normalized, _ = ExtractionAgent().run(candidates, {"mode": "live"})
        researched, _, _ = ResearchAgent().run(normalized, {"mode": "live"})
        researched, _ = RankingAgent().run(researched, brief)
        matches = [product for product in researched if product_identity(product)[0] == key
                   and verified_price_offer(product, key, now_iso())]
        for product in matches:
            product["id"] = f"cross-store-{hashlib.sha1(product['url'].encode()).hexdigest()[:12]}"
        report["matched"] = len(matches)
        report["status"] = "matched" if matches else "no_match"
        return matches
    except Exception:
        report["status"] = "unavailable"
        return []


def _cross_store_research_event(event: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
    report = source_meta.get("cross_store") or {}
    if report.get("status") == "matched":
        detail = f"; exact-item lookup confirmed {report['matched']} other retailer offer(s) from {report['attempted']} pages"
    elif report.get("status") == "no_match":
        detail = f"; checked {report['attempted']} other retailer pages with no confirmed same-item offer"
    elif report.get("status") == "no_candidates":
        detail = "; exact-item lookup found no other retailer product pages"
    elif report.get("status") == "unavailable":
        detail = "; exact-item lookup was unavailable"
    else:
        return event
    return {**event, "detail": str(event.get("detail") or "") + detail}


def _budget_opportunity(products: list[dict[str, Any]], brief: dict[str, Any]) -> dict[str, Any] | None:
    """Surface a small, evidence-backed stretch without silently changing the plan."""
    budget = max(_money(brief.get("budget")), 1)
    candidates = [
        product
        for product in products
        if product.get("budget_fit") is False
        and product.get("category_fit") is not False
        and product.get("delivery_fit") is not False
        and product.get("stock_fit") is not False
        and _money(product.get("line_total")) <= round(budget * 1.1)
    ]
    if not candidates:
        return None
    candidate = max(candidates, key=lambda product: (product.get("match_score") or 0, -(product.get("line_total") or 10**9)))
    line_total = _money(candidate.get("line_total"))
    extra = max(0, line_total - budget)
    price_history = candidate.get("price_history") if isinstance(candidate.get("price_history"), dict) else {}
    evidence = price_history.get("trend_label") or "delivery and stock still fit the brief"
    return {
        "product_id": str(candidate.get("id") or ""),
        "name": str(candidate.get("name") or "Nearby fit")[:180],
        "total": line_total,
        "extra": extra,
        "delivery_label": str(candidate.get("delivery_label") or "Delivery remains within the requested window")[:120],
        "reason": f"{evidence}; the option scores {candidate.get('match_score') or 0}% against the brief",
    }


def _merge_refinement_intent(previous: dict[str, Any], text: str) -> dict[str, Any]:
    brief = copy.deepcopy(previous)
    follow_up = str(text or "").strip()
    lowered = follow_up.lower()
    if not follow_up:
        return brief
    clarification_keys = {
        str(item.get("key")) for item in (brief.get("clarifications") or []) if isinstance(item, dict)
    }

    delta_match = re.search(r"(?:increase|raise|add|extra|more)\D{0,18}(?:₹|rs\.?|inr)?\s*([\d,]+)", follow_up, flags=re.IGNORECASE)
    explicit_budget = _parse_budget(follow_up)
    if explicit_budget is None and "budget" in clarification_keys:
        explicit_budget = _parse_budget(f"budget {follow_up}")
    if delta_match and any(term in lowered for term in ("budget", "spend", "pay", "price")):
        brief["budget"] = _money(brief.get("budget")) + int(delta_match.group(1).replace(",", ""))
    elif explicit_budget is not None:
        brief["budget"] = explicit_budget

    quantity_match = re.search(r"\b(\d{1,3})(?:\s+[a-z][a-z0-9&'-]*){0,3}\s+(?:units?|items?|pieces?|pairs?|chairs?|shirts?)\b", follow_up, flags=re.IGNORECASE)
    if quantity_match:
        brief["quantity"] = max(1, min(int(quantity_match.group(1)), 99))
    brand = _parse_brand(follow_up)
    if brand:
        brief["brand"] = brand
    parsed_follow_up_days = _parse_days(follow_up)
    if parsed_follow_up_days is not None:
        days = parsed_follow_up_days
        brief["arrive_by_days"] = days
        brief["arrive_by"] = f"within {days} days"
    location_match = _location_match(follow_up)
    if location_match:
        location = location_match.group(1).strip(" .,\"")
        brief["location"] = "Bengaluru" if location.lower() == "bangalore" else location
    parsed_color = _parse_color(follow_up)
    parsed_size = _parse_size(follow_up)
    parsed_fabric = _parse_fabric(follow_up)
    parsed_pincode = _parse_pincode(follow_up)
    parsed_style = _parse_occasion_or_style(follow_up)
    if parsed_color:
        brief["color"] = parsed_color
    if parsed_size:
        brief["size"] = parsed_size
    if parsed_fabric:
        brief["fabric"] = parsed_fabric
    if parsed_pincode:
        brief["pincode"] = parsed_pincode
    if parsed_style:
        brief["style"] = parsed_style
    bare_location_answered = False
    if (
        not location_match
        and "location" in clarification_keys
        and not parsed_color
        and not parsed_size
        and not parsed_pincode
        and parsed_follow_up_days is None
        and re.fullmatch(r"[a-z][a-z .'-]{2,40}", follow_up, flags=re.IGNORECASE)
    ):
        location = follow_up.strip(" .,\"")
        brief["location"] = "Bengaluru" if location.lower() == "bangalore" else location
        bare_location_answered = True
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
    existing_keys = {str(item.get("key")) for item in (brief.get("clarifications") or []) if isinstance(item, dict)}
    if existing_keys:
        answered = set()
        if explicit_budget is not None:
            answered.add("budget")
        if location_match or bare_location_answered:
            answered.add("location")
        if parsed_follow_up_days is not None:
            answered.add("delivery")
        if parsed_color:
            answered.add("color")
        if parsed_size:
            answered.add("size")
        if parsed_pincode:
            answered.add("pincode")
        brief["clarifications"] = [
            item for item in (brief.get("clarifications") or []) if str(item.get("key")) not in answered
        ]
    remaining_keys = {
        str(item.get("key"))
        for item in (brief.get("clarifications") or [])
        if isinstance(item, dict)
    }
    is_fashion = any(token in str(brief.get("category") or "").lower() for token in ("fashion", "cloth", "dress", "shirt", "shoe", "outfit"))
    location_confirmed = bool(location_match or bare_location_answered or "location" not in clarification_keys)
    if is_fashion and location_confirmed and not brief.get("pincode") and "pincode" not in remaining_keys:
        brief.setdefault("clarifications", []).append({"key": "pincode", "question": "What delivery pincode should I use to verify the delivery promise?"})
    arrival_date = (_india_today() + timedelta(days=brief["arrive_by_days"])).isoformat() if parsed_follow_up_days is not None else None
    _refresh_mission(brief, arrival_date)
    return brief


def _clarification_response(
    brief: dict[str, Any],
    workflow: list[dict[str, Any]],
    source: dict[str, Any] | None = None,
    *,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Persist and return a resumable clarification checkpoint."""
    questions = [item for item in brief.get("clarifications") or [] if isinstance(item, dict)]
    for index in range(2, len(workflow)):
        agent = WORKFLOW_AGENTS[index] if index < len(WORKFLOW_AGENTS) else str(workflow[index].get("agent") or "Research agent")
        workflow[index] = {
            "agent": agent,
            "status": "waiting",
            "detail": "Waiting for the shopper to answer the clarification questions before retailer research",
        }
    search_id = f"search-{uuid.uuid4().hex}"
    source_meta = copy.deepcopy(source) if isinstance(source, dict) else {}
    source_meta.update({
        "mode": "clarification",
        "requires_clarification": True,
        "clarification_keys": [str(item.get("key")) for item in questions],
    })
    db.save_search(search_id, brief.get("raw_text") or "", brief, workflow, products=[], source=source_meta)
    question_text = " ".join(str(item.get("question") or "") for item in questions).strip()
    return {
        "status": "needs_clarification",
        "search_id": search_id,
        "intent": brief,
        "clarifications": questions,
        "products": [],
        "selected_product_ids": [],
        "summary": {
            "total": 0,
            "item_count": 0,
            "delivery_label": brief.get("arrive_by") or "Delivery timing to confirm",
            "opportunity": None,
        },
        "workflow": workflow,
        "source": source_meta,
        "conversation": [
            {"role": "user", "text": user_text or brief.get("raw_text") or ""},
            {"role": "assistant", "text": f"Before I search, I need a few details. {question_text}"},
        ],
    }


def run_refinement(payload: dict[str, Any]) -> dict[str, Any]:
    search_id = payload.get("search_id")
    if not isinstance(search_id, str) or not search_id.strip() or len(search_id) > 120:
        raise ValueError("A previous search is required before refining the shortlist")
    previous = db.get_search(search_id.strip())
    if not previous:
        raise ValueError("Previous search not found")
    if not previous.get("trusted"):
        raise ValueError("Previous search is not verified")
    previous_intent = previous["intent"]
    previous_products = previous["products"]
    previous_source = previous["source"]
    text = str(payload.get("text") or payload.get("query") or "").strip()
    if not previous_intent:
        raise ValueError("A previous search is required before refining the shortlist")
    if not text:
        raise ValueError("Tell Artha what you would like to change")
    brief = copy.deepcopy(previous_intent)
    mission = _mission_input(payload)
    if mission is not None:
        submitted = payload["mission"]
        for field in ("occasion", "budget", "pincode", "size", "color", "style"):
            if field in submitted:
                brief[field] = mission[field]
        deadline = mission.get("arrive_by_date")
        if deadline:
            arrive_by_date = date.fromisoformat(deadline)
            brief["arrive_by_days"] = (arrive_by_date - _india_today()).days
            brief["arrive_by"] = f"by {arrive_by_date.strftime('%d %b').lstrip('0')}"
        elif "arrive_by_date" in submitted and isinstance(previous_intent.get("mission"), dict) and previous_intent["mission"].get("arrive_by_date"):
            brief["arrive_by_days"] = None
            brief["arrive_by"] = None
        _refresh_mission(brief, (deadline or "") if "arrive_by_date" in submitted else None)
        answered = {
            "budget": mission.get("budget") is not None,
            "location": bool(mission.get("pincode")),
            "pincode": bool(mission.get("pincode")),
            "delivery": bool(deadline),
            "color": bool(mission.get("color")),
            "size": bool(mission.get("size")),
        }
        brief["clarifications"] = [
            question for question in (brief.get("clarifications") or [])
            if isinstance(question, dict) and not answered.get(str(question.get("key")))
        ]
        remaining = {str(question.get("key")) for question in brief["clarifications"]}
        if "budget" in submitted and mission["budget"] is None and "budget" not in remaining:
            brief["clarifications"].append({"key": "budget", "question": "What is the maximum you would like to spend?"})
        if "arrive_by_date" in submitted and not deadline and brief.get("arrive_by_days") is None and "delivery" not in remaining:
            brief["clarifications"].append({"key": "delivery", "question": "When do you need it by?"})
    brief = _merge_refinement_intent(brief, text)
    location_changed = str(previous_intent.get("location") or "").strip().casefold() != str(brief.get("location") or "").strip().casefold()
    old_pincode = str(previous_intent.get("pincode") or "").strip()
    if location_changed and old_pincode and str(brief.get("pincode") or "").strip() == old_pincode:
        # A copied pincode cannot verify delivery to a newly named city.
        brief["pincode"] = None
        _refresh_mission(brief)
        is_fashion = any(token in str(brief.get("category") or "").lower() for token in ("fashion", "cloth", "dress", "shirt", "shoe", "outfit"))
        if is_fashion and not any(isinstance(question, dict) and question.get("key") == "pincode" for question in brief.get("clarifications") or []):
            brief.setdefault("clarifications", []).append({"key": "pincode", "question": "What delivery pincode should I use to verify the delivery promise?"})
    products = copy.deepcopy([product for product in previous_products if isinstance(product, dict)])
    destination_changed = location_changed or old_pincode != str(brief.get("pincode") or "").strip()
    hard_changed = any(
        str(previous_intent.get(field)).casefold() != str(brief.get(field)).casefold()
        for field in ("budget", "arrive_by_days", "pincode", "size", "color")
    )
    rediscover = False
    if products and destination_changed:
        # Delivery evidence is tied to the destination used for the original search.
        products = []
        rediscover = True
    elif products and hard_changed and brief.get("clarifications"):
        products = []
    elif products and hard_changed:
        variant_changed = any(brief.get(field) and str(previous_intent.get(field)).casefold() != str(brief.get(field)).casefold() for field in ("color", "size"))
        checked, _ = RankingAgent().run(copy.deepcopy(products), brief)
        rediscover = variant_changed or not any(product.get("eligible") is not False for product in checked)
        if rediscover:
            products = []

    if not products and brief.get("clarifications"):
        workflow = [
            {
                "agent": "Follow-up agent",
                "status": "waiting",
                "detail": "The follow-up was understood; more details are needed before retailer research",
            },
            {
                "agent": "Location agent",
                "status": "complete",
                "detail": "Using the delivery location already present in the brief",
            },
        ]
        return _clarification_response(brief, workflow, previous_source, user_text=text)

    if not products:
        # A clarification-first search has no product set to reuse. Once the
        # shopper answers everything, perform the normal discovery pipeline
        # from the structured intent rather than reparsing it from scratch.
        post_url = _reference_url(brief.get("post_url"))
        workflow = initial_workflow()
        workflow[0] = {"agent": "Follow-up agent", "status": "complete", "detail": "Changed constraints triggered fresh retailer research" if rediscover else "Structured answers completed the shopping brief"}
        workflow[1] = {"agent": "Location agent", "status": "complete", "detail": "Using the delivery location confirmed in the brief"}
        raw_products, search_event, source_meta = SearchAgent().run(brief, post_url)
        workflow[2] = search_event
        products, evidence_event = ExtractionAgent().run(raw_products, source_meta)
        workflow[3] = evidence_event
        products, research_event, source_meta = ResearchAgent().run(products, source_meta)
        other_offers = _targeted_cross_store_offers(products, brief, source_meta)
        workflow[4] = _cross_store_research_event(research_event, source_meta)
        products, _ = RankingAgent().run(products + other_offers, brief)
        products = enrich_price_evidence(db, products, source_mode=source_meta.get("mode"))
        products, analysis_event = AnalysisAgent().run(products, brief)
        workflow[5] = analysis_event
        products, ranking_event = RankingAgent().run(products, brief)
        workflow[6] = ranking_event
        brief["decision"] = _mission_decision(products, brief)
        search_id = f"search-{uuid.uuid4().hex}"
        source = copy.deepcopy(source_meta)
        source["refined"] = True
        db.save_search(search_id, brief["raw_text"], brief, workflow, products=products, source=source)
        selected_products = _decision_selection(products, brief["decision"])
        latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 0
        return {
            "status": "complete",
            "search_id": search_id,
            "intent": brief,
            "products": products,
            "selected_product_ids": [product["id"] for product in selected_products],
            "summary": {
                "total": sum(_money(product.get("line_total")) or _money(product.get("total_price")) for product in selected_products),
                "item_count": len(selected_products),
                "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer",
                "opportunity": _budget_opportunity(products, brief),
            },
            "workflow": workflow,
            "source": source,
            "conversation": [
                {"role": "user", "text": text},
                {"role": "assistant", "text": "Thanks — I have enough detail now and searched the retailer sources."},
            ],
        }

    products, analysis_event = AnalysisAgent().run(products, brief)
    products, ranking_event = RankingAgent().run(products, brief)
    brief["decision"] = _mission_decision(products, brief)
    search_id = f"search-{uuid.uuid4().hex}"
    follow_up_event = {
        "agent": "Follow-up agent",
        "status": "complete",
        "detail": "Kept the completed research set and applied the new preference without repeating retailer discovery",
    }
    workflow = [follow_up_event, analysis_event, ranking_event]
    source = copy.deepcopy(previous_source)
    source["refined"] = True
    db.save_search(search_id, brief["raw_text"], brief, workflow, products=products, source=source)
    selected_products = [] if brief.get("clarifications") else _decision_selection(products, brief["decision"])
    latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 5
    return {
        "status": "complete",
        "search_id": search_id,
        "intent": brief,
        "products": products,
        "selected_product_ids": [product["id"] for product in selected_products],
        "summary": {
            "total": sum(_money(product.get("line_total")) or _money(product.get("total_price")) for product in selected_products),
            "item_count": len(selected_products),
            "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer",
            "opportunity": _budget_opportunity(products, brief),
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
    if brief.get("clarifications"):
        emit()
        return _clarification_response(brief, workflow, {"mode": "clarification"}, user_text=brief.get("raw_text"))
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
    if source_meta.get("mode") == "live":
        set_stage(4, "working", "Checking exact-item offers at other retailers")
    other_offers = _targeted_cross_store_offers(products, brief, source_meta)
    workflow[4] = _cross_store_research_event(research_event, source_meta)
    emit()
    products, _ = RankingAgent().run(products + other_offers, brief)
    products = enrich_price_evidence(db, products, source_mode=source_meta.get("mode"))
    set_stage(5, "working", "Cross-checking review and price-history signals")
    products, analysis_event = AnalysisAgent().run(products, brief)
    workflow[5] = analysis_event
    emit()
    set_stage(6, "working", "Ranking options against every stated constraint")
    products, ranking_event = RankingAgent().run(products, brief)
    workflow[6] = ranking_event
    brief["decision"] = _mission_decision(products, brief)
    emit()
    search_id = f"search-{uuid.uuid4().hex}"
    db.save_search(search_id, brief["raw_text"], brief, workflow, products=products, source=source_meta)
    selected_products = [] if brief.get("clarifications") else _decision_selection(products, brief["decision"])
    total = sum(_money(product.get("line_total")) or _money(product.get("total_price")) or _money(product.get("price")) for product in selected_products)
    latest_delivery = max((product.get("delivery_days") or 0) for product in selected_products) if selected_products else 5
    return {
        "status": "complete",
        "search_id": search_id,
        "intent": brief,
        "products": products,
        "selected_product_ids": [product["id"] for product in selected_products],
        "summary": {"total": total, "item_count": len(selected_products), "delivery_label": f"All known deliveries arrive by {_date_label(latest_delivery)}" if latest_delivery else "Confirm delivery at retailer", "opportunity": _budget_opportunity(products, brief)},
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
        "color": str(product.get("color") or "")[:60],
        "size": str(product.get("size") or "")[:60],
        "fabric": str(product.get("fabric") or "")[:60],
        "pincode": str(product.get("pincode") or "")[:6],
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
    search_id = str(payload.get("search_id") or "").strip()
    selected = payload.get("products")
    canonical = {str(product.get("id")): product for product in db.get_search_products(search_id) if isinstance(product, dict)} if search_id else {}
    requested_ids = [str(product.get("id")) for product in selected if isinstance(product, dict) and product.get("id")] if isinstance(selected, list) else []
    if not search_id or not requested_ids or any(product_id not in canonical for product_id in requested_ids):
        raise ValueError("Select products from a saved search before saving a purchase plan")
    products = [_safe_plan_item(canonical[product_id]) for product_id in dict.fromkeys(requested_ids)]
    products = [product for product in products if product["url"]]
    if not products:
        raise ValueError("Select at least one linked retailer product before saving a purchase plan")
    timestamp = now_iso()
    plan = {
        "id": f"PLAN-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}",
        "user_id": user_id,
        "search_id": search_id,
        "status": "ready_for_checkout",
        "total": sum(product["line_total"] for product in products),
        "items": products,
        "created_at": timestamp,
        "updated_at": timestamp,
        "notice": "Open each retailer link to complete checkout on that retailer's secure site. Artha never handles payment credentials.",
    }
    return db.save_purchase_plan(plan)
