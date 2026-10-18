"""Stateful, local-first voice & text shopping conversation manager.

Implements:
- Home-screen greeting ("What are you looking for today, Arjeet?")
- One-question-at-a-time clarification across destination, occasion, product, budget, size, fit, and style/reference
- Intelligent shopping history reuse, conflict detection/confirmation, and temporary vs. long-term preference scoping
- Instagram friend post resolution, screenshot capture, post/item confirmation, local clothing attribute analysis, and retailer search
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .db import db, now_iso
from .profile import analyze_preference_history, save_confirmed_preference
from .social import (
    analyze_clothing_reference,
    resolve_instagram_reference,
    save_uploaded_instagram_reference,
)
from .workflow import (
    _parse_budget,
    _parse_color,
    _parse_fabric,
    _parse_pincode,
    _parse_size,
    run_search,
)


def _resolve_shopper_first_name(user_id: str, fallback: str = "Arjeet") -> str:
    try:
        with db._connect() as conn:
            row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
            if row and row["name"]:
                first = str(row["name"]).strip().split()[0]
                if first and first.lower() not in {"shopper", "shopper-local", "local", "test"}:
                    return first
            arjeet_row = conn.execute("SELECT name FROM users WHERE lower(name) LIKE 'arjeet%' LIMIT 1").fetchone()
            if arjeet_row and arjeet_row["name"]:
                return str(arjeet_row["name"]).strip().split()[0]
    except Exception:
        pass
    return fallback


def _detect_destination_and_occasion(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    dest_match = re.search(
        r"\b(?:going\s+to|trip\s+to|heading\s+to|travel(?:ling)?\s+to|vacation\s+in|for\s+my\s+trip\s+to)\s+([a-z][a-z\s]{1,24}?)(?=\s+(?:and|to|for|in|under|with|trip|next|this)\b|[,.;!?]|$)",
        lowered,
    )
    destination = None
    if dest_match:
        candidate = dest_match.group(1).strip()
        if candidate not in {"buy", "get", "shop", "find", "a", "the"}:
            destination = candidate.title()
    elif re.search(r"\bgoa\b", lowered):
        destination = "Goa"

    occasion = None
    if destination:
        occasion = f"{destination} trip"
    elif re.search(r"\b(beach|vacation|holiday|resort|travel|trip)\b", lowered):
        occasion = "Vacation / Travel"
    elif re.search(r"\b(office|work|formal|meeting)\b", lowered):
        occasion = "Office"
    elif re.search(r"\b(wedding|party|festive|dinner)\b", lowered):
        occasion = "Party / Event"
    return destination, occasion


def _detect_product(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    for pattern, product_label, category in (
        (r"\b(?:t[\s-]*shirts?|tees?)\b", "T-shirt", "T-shirt"),
        (r"\b(?:overshirts?|linen\s+shirts?|casual\s+shirts?|shirts?)\b", "Shirt", "Shirt"),
        (r"\b(?:hoodies?|sweatshirts?)\b", "Hoodie", "Clothing"),
        (r"\b(?:shorts?|half\s+pants?)\b", "Shorts", "Shorts"),
        (r"\b(?:trousers?|pants?|chinos?|jeans)\b", "Trousers", "Pants"),
        (r"\b(?:sneakers?|shoes?|loafers?|sandals?)\b", "Shoes", "Footwear"),
        (r"\b(?:office\s+chairs?|ergonomic\s+chairs?|chairs?)\b", "Office chair", "Office chair"),
    ):
        if re.search(pattern, lowered):
            return product_label, category
    return None, None


def _detect_fit(text: str) -> str | None:
    lowered = text.lower()
    for fit in ("oversized", "relaxed", "regular", "slim", "boxy", "tailored"):
        if re.search(rf"\b{fit}\b", lowered):
            return fit
    return None


def _friend_style_reference(text: str) -> str | None:
    match = re.search(
        r"\b(?:my\s+)?friend\s+([A-Za-z][A-Za-z-]{1,30})(?:['’]s)?[^.!?]{0,60}\b(?:dressing\s+sense|style|fashion|outfit|look)\b",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).title() if match else None


def _is_temporary_choice_phrasing(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"\b(just\s+for\s+this|only\s+for\s+this|this\s+time|temporary|for\s+this\s+trip\s+only|for\s+a\s+friend|instead\s+of\s+my\s+usual)\b",
            lowered,
        )
    )


def _is_permanent_choice_phrasing(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"\b(my\s+usual|always\s+use|save\s+as\s+my|update\s+my\s+usual|from\s+now\s+on|permanently)\b",
            lowered,
        )
    )


def _default_state(user_id: str, history: dict[str, Any]) -> dict[str, Any]:
    return {
        "product": None,
        "category": None,
        "destination": None,
        "occasion": None,
        "budget": None,
        "size": None,
        "size_confirmed": False,
        "size_prompted_value": None,
        "fit": None,
        "color": None,
        "fabric": None,
        "style": None,
        "style_prompted": False,
        "location": history.get("usual_location") or "Bengaluru",
        "pincode": history.get("usual_pincode") or "560038",
        "arrive_by_days": 5,
        "preference_scope": {},
        "temporary_overrides": {},
        "confirmed_long_term": {},
        "conflicts_detected": history.get("conflicts") or {},
        "awaiting_instagram_handle": False,
        "awaiting_post_confirmation": False,
        "friend_name": None,
        "instagram_handle": None,
        "instagram_posts": [],
        "selected_reference": None,
        "reference_attributes": None,
        "search_id": None,
        "status": "collecting_brief",
    }


def get_or_start_session(
    user_id: str,
    *,
    session_id: str | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    history = analyze_preference_history(user_id)
    first_name = _resolve_shopper_first_name(user_id)
    greeting = f"What are you looking for today, {first_name}?"

    if session_id and not reset:
        existing = db.get_conversation_session(session_id, user_id)
        if existing:
            return {
                **existing,
                "session_id": existing.get("id"),
                "greeting": greeting,
                "history": history,
            }

    new_id = f"conv-{uuid.uuid4().hex[:16]}"
    state = _default_state(user_id, history)
    messages = [
        {
            "id": f"assistant-init-{ new_id }",
            "role": "assistant",
            "text": greeting,
            "created_at": now_iso(),
        }
    ]
    saved = db.save_conversation_session(new_id, user_id, state, messages)
    return {
        **saved,
        "session_id": saved.get("id"),
        "greeting": greeting,
        "history": history,
    }


def _execute_search_from_state(
    user_id: str,
    session_id: str,
    state: dict[str, Any],
    messages: list[dict[str, Any]],
    history: dict[str, Any],
) -> dict[str, Any]:
    ref_attrs = state.get("reference_attributes") or {}
    product_noun = state.get("product") or ref_attrs.get("category") or "T-shirt"
    color = state.get("color") or ref_attrs.get("color") or (history.get("palette")[0] if history.get("palette") else "olive")
    fit = state.get("fit") or ref_attrs.get("fit") or "relaxed"
    pattern = ref_attrs.get("pattern") or ""
    fabric = state.get("fabric") or ref_attrs.get("fabric") or "cotton"
    style = state.get("style") or ref_attrs.get("theme") or (history.get("vibes")[0] if history.get("vibes") else "relaxed casual")
    size = state.get("size") or history.get("usual_sizes", {}).get("top") or "M"
    budget = state.get("budget") or 1500
    location = state.get("location") or history.get("usual_location") or "Bengaluru"
    pincode = state.get("pincode") or history.get("usual_pincode") or "560038"
    days = state.get("arrive_by_days") or 5

    query_parts = [
        fit,
        pattern if pattern and pattern != "solid" else "",
        color,
        fabric,
        product_noun,
        f"size {size}",
        f"under ₹{budget}",
        f"delivered to {location} {pincode}",
        f"within {days} days",
    ]
    if state.get("occasion"):
        query_parts.append(f"for {state['occasion']}")
    full_query = " ".join(part for part in query_parts if part).strip()

    payload: dict[str, Any] = {
        "text": full_query,
        "user_id": user_id,
        "use_profile": True,
        "location": location,
        "pincode": pincode,
        "mission": {
            "occasion": state.get("occasion") or "Goa trip",
            "budget": budget,
            "pincode": pincode,
            "size": size,
            "color": color,
            "style": style,
        },
    }
    selected_ref = state.get("selected_reference")
    if isinstance(selected_ref, dict) and selected_ref.get("post_url"):
        payload["post_url"] = selected_ref["post_url"]

    search_result = run_search(payload)
    # Attach reference_attributes and re-rank if reference attributes were extracted
    if ref_attrs and search_result.get("products"):
        from .workflow import RankingAgent, _mission_decision
        intent = search_result.get("intent") or {}
        intent["reference_attributes"] = ref_attrs
        intent["preference_scope"] = state.get("preference_scope") or {}
        intent["temporary_overrides"] = state.get("temporary_overrides") or {}
        ranked_products, _ = RankingAgent().run(search_result["products"], intent)
        intent["decision"] = _mission_decision(ranked_products, intent)
        search_result["products"] = ranked_products
        search_result["intent"] = intent
        if search_result.get("search_id"):
            db.save_search(
                search_result["search_id"],
                intent.get("raw_text") or full_query,
                intent,
                search_result.get("workflow") or [],
                products=ranked_products,
                source=search_result.get("source") or {},
            )

    products = search_result.get("products") or []
    state["search_id"] = search_result.get("search_id")
    state["status"] = "results_ready"

    if products:
        top = products[0]
        price_str = f"₹{top.get('price'):,}" if top.get("price") else "price on retailer page"
        ref_clause = (
            f" matching the {ref_attrs.get('color', '')} {ref_attrs.get('fit', '')} {ref_attrs.get('category', product_noun).lower()} from @{state.get('instagram_handle') or state.get('friend_name') or 'Instagram'}"
            if ref_attrs else ""
        )
        reply_text = (
            f"I found {len(products)} source-backed option{'s' if len(products) != 1 else ''}{ref_clause} "
            f"within your ₹{budget:,} budget in size {size}. "
            f"Top pick: {top.get('name')} at {price_str} from {top.get('seller')}. "
            f"{top.get('match_explanation') or ''}"
        ).strip()
    else:
        reply_text = (
            f"I checked the supported retailers for a {color} {product_noun} under ₹{budget:,} in size {size}, "
            "but no verified product page cleared every constraint right now. You can widen the budget or adjust the style to retry."
        )

    assistant_msg = {
        "id": f"assistant-{uuid.uuid4().hex[:10]}",
        "role": "assistant",
        "text": reply_text,
        "created_at": now_iso(),
        "search_id": search_result.get("search_id"),
    }
    messages.append(assistant_msg)
    saved = db.save_conversation_session(session_id, user_id, state, messages)
    return {
        "session_id": session_id,
        "reply": reply_text,
        "state": saved["state"],
        "messages": saved["messages"],
        "history": history,
        "search_result": search_result,
        "instagram_posts": state.get("instagram_posts") or [],
        "selected_reference": state.get("selected_reference"),
        "reference_attributes": state.get("reference_attributes"),
    }


def process_conversation_turn(
    user_id: str,
    text: str,
    *,
    session_id: str | None = None,
    reference_image: dict[str, str] | None = None,
    reference_url: str | None = None,
) -> dict[str, Any]:
    """Process one user turn in the home-screen voice/text shopping conversation."""
    session = get_or_start_session(user_id, session_id=session_id)
    session_id = session["id"]
    state: dict[str, Any] = dict(session["state"])
    messages: list[dict[str, Any]] = list(session["messages"])
    history = session["history"]
    usual_top_size = history.get("usual_sizes", {}).get("top") or "M"

    clean_text = str(text or "").strip()
    if clean_text:
        messages.append({
            "id": f"user-{uuid.uuid4().hex[:10]}",
            "role": "user",
            "text": clean_text,
            "created_at": now_iso(),
        })

    friend_name = _friend_style_reference(clean_text)
    if friend_name:
        state["friend_name"] = friend_name

    # 1. Extract structured fields from the user's message
    dest, occ = _detect_destination_and_occasion(clean_text)
    if dest:
        state["destination"] = dest
    if occ:
        state["occasion"] = occ

    prod, cat = _detect_product(clean_text)
    if prod:
        state["product"] = prod
        state["category"] = cat

    parsed_budget = _parse_budget(clean_text)
    if parsed_budget is None and state.get("last_question_key") in {"budget", "budget_and_size"}:
        parsed_budget = _parse_budget(f"budget {clean_text}")
    if parsed_budget is not None and parsed_budget > 0:
        state["budget"] = parsed_budget

    parsed_fit = _detect_fit(clean_text)
    if parsed_fit:
        state["fit"] = parsed_fit

    parsed_color = _parse_color(clean_text)
    if parsed_color:
        state["color"] = parsed_color

    parsed_fabric = _parse_fabric(clean_text)
    if parsed_fabric:
        state["fabric"] = parsed_fabric

    parsed_pin = _parse_pincode(clean_text)
    if parsed_pin:
        state["pincode"] = parsed_pin
        if parsed_pin != history.get("usual_pincode"):
            state.setdefault("preference_scope", {})["pincode"] = "temporary_current_purchase"
            state.setdefault("temporary_overrides", {})["pincode"] = parsed_pin

    # Check explicit delivery city override vs trip destination
    deliver_match = re.search(r"\b(?:deliver(?:ed|y)?\s+to|ship\s+to)\s+([a-zA-Z]+)", clean_text, flags=re.IGNORECASE)
    if deliver_match:
        new_loc = deliver_match.group(1).strip().title()
        if new_loc.lower() == "bangalore":
            new_loc = "Bengaluru"
        state["location"] = new_loc
        if new_loc.lower() != str(history.get("usual_location") or "Bengaluru").lower():
            state.setdefault("preference_scope", {})["location"] = "temporary_current_purchase"
            state.setdefault("temporary_overrides", {})["location"] = new_loc

    # Size extraction & conflict/temporary vs long-term resolution
    parsed_size = _parse_size(clean_text)
    if parsed_size:
        size_upper = {"small": "S", "medium": "M", "large": "L"}.get(parsed_size.lower(), parsed_size.upper())
        state["size"] = size_upper
        state["size_confirmed"] = True
        is_temp = _is_temporary_choice_phrasing(clean_text) or (
            size_upper != usual_top_size and not _is_permanent_choice_phrasing(clean_text)
        )
        if is_temp:
            state.setdefault("preference_scope", {})["size"] = "temporary_current_purchase"
            state.setdefault("temporary_overrides", {})["size"] = size_upper
        else:
            state.setdefault("preference_scope", {})["size"] = "confirmed_long_term"
            state.setdefault("confirmed_long_term", {})["size"] = size_upper
            save_confirmed_preference(user_id, size_top=size_upper, is_temporary=False)
    elif state.get("size_prompted_value") and not state.get("size_confirmed"):
        # If the assistant asked "Do you have a budget in mind? Should I use your usual size M?"
        # and the user replied with their budget ("Around ₹1,500") or "yes" without rejecting size M:
        if not re.search(r"\b(no|different\s+size|not\s+m|wrong\s+size)\b", clean_text.lower()):
            if parsed_budget is not None or re.search(r"\b(yes|yeah|yep|sure|ok|okay|usual|use\s+m)\b", clean_text.lower()):
                confirmed_sz = str(state["size_prompted_value"]).upper()
                state["size"] = confirmed_sz
                state["size_confirmed"] = True
                state.setdefault("preference_scope", {})["size"] = "confirmed_long_term"
                state.setdefault("confirmed_long_term", {})["size"] = confirmed_sz
                save_confirmed_preference(user_id, size_top=confirmed_sz, is_temporary=False)

    # 2. Check if user uploaded a reference screenshot or selected one of the captured Instagram posts
    if reference_image and reference_image.get("data_base64"):
        saved_ref = save_uploaded_instagram_reference(
            user_id,
            image_base64=reference_image["data_base64"],
            mime_type=reference_image.get("mime_type") or "image/jpeg",
            source_url=reference_url or "",
            friend_name=state.get("friend_name") or "Paras",
            handle=state.get("instagram_handle") or "",
            caption=clean_text,
        )
        state["instagram_posts"] = [saved_ref, *[p for p in (state.get("instagram_posts") or []) if p.get("id") != saved_ref["id"]]][:5]
        analysis = analyze_clothing_reference(
            user_id,
            reference_id=saved_ref["id"],
            reference_image=reference_image,
            item_hint=state.get("product") or "T-shirt",
            caption=clean_text,
        )
        state["selected_reference"] = saved_ref
        state["reference_attributes"] = analysis["attributes"]
        state["awaiting_instagram_handle"] = False
        state["awaiting_post_confirmation"] = False
        state["style"] = analysis["attributes"].get("theme") or "coastal casual"
        return _execute_search_from_state(user_id, session_id, state, messages, history)

    if state.get("awaiting_post_confirmation") and state.get("instagram_posts"):
        posts = state["instagram_posts"]
        post_index_match = re.search(r"\b(?:post|option|image|photo|number|#)?\s*([1-5])\b|\b(first|second|third|fourth|fifth|latest)\b", clean_text.lower())
        word_to_idx = {"first": 0, "latest": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
        idx = None
        if post_index_match:
            if post_index_match.group(1):
                idx = int(post_index_match.group(1)) - 1
            elif post_index_match.group(2):
                idx = word_to_idx.get(post_index_match.group(2), 0)
        elif re.search(r"\b(yes|confirm|that\s+one|this\s+one|t-?shirt|shirt)\b", clean_text.lower()):
            idx = 0
        if idx is not None and 0 <= idx < len(posts):
            chosen_post = posts[idx]
            analysis = analyze_clothing_reference(
                user_id,
                reference_id=chosen_post["id"],
                item_hint=state.get("product") or "T-shirt",
                caption=chosen_post.get("caption") or clean_text,
            )
            state["selected_reference"] = chosen_post
            state["reference_attributes"] = analysis["attributes"]
            state["awaiting_post_confirmation"] = False
            state["style"] = analysis["attributes"].get("theme")
            return _execute_search_from_state(user_id, session_id, state, messages, history)

    # 3. Check if user mentioned an Instagram post / friend or answered an Instagram handle prompt
    insta_triggered = bool(
        re.search(r"\b(instagram|insta|reel|post)\b", clean_text, flags=re.IGNORECASE)
        or re.search(r"https?://(?:www\.)?instagram\.com/", clean_text, flags=re.IGNORECASE)
        or (state.get("awaiting_instagram_handle") and (re.search(r"@[A-Za-z0-9._]+", clean_text) or re.fullmatch(r"[A-Za-z0-9._]{3,30}", clean_text)))
        or friend_name
    )
    if insta_triggered or reference_url:
        target_input = reference_url or clean_text
        friend = state.get("friend_name") or ""
        resolved = resolve_instagram_reference(user_id, target_input, friend_name=friend, max_posts=5)
        if resolved.get("friend_name"):
            state["friend_name"] = resolved["friend_name"]
        if resolved.get("handle"):
            state["instagram_handle"] = resolved["handle"]

        if resolved.get("success") and resolved.get("posts"):
            state["instagram_posts"] = resolved["posts"]
            state["awaiting_instagram_handle"] = False
            state["awaiting_post_confirmation"] = True
            state["style_prompted"] = True
            state["last_question_key"] = "confirm_instagram_post"
            reply_text = (
                f"I retrieved {len(resolved['posts'])} recent post screenshot(s) from @{resolved.get('handle') or state.get('friend_name') or 'Instagram'} "
                f"and saved them locally with their source URLs and capture times. "
                f"Please select the post below and confirm that you want to match the {state.get('product') or 'T-shirt'}."
            )
            messages.append({
                "id": f"assistant-{uuid.uuid4().hex[:10]}",
                "role": "assistant",
                "text": reply_text,
                "created_at": now_iso(),
            })
            saved = db.save_conversation_session(session_id, user_id, state, messages)
            return {
                "session_id": session_id,
                "reply": reply_text,
                "state": saved["state"],
                "messages": saved["messages"],
                "history": history,
                "instagram_posts": resolved["posts"],
                "instagram_status": resolved.get("status"),
            }

        # Ambiguous handle, missing handle, login required, or private profile
        state["awaiting_instagram_handle"] = True
        state["style_prompted"] = True
        state["last_question_key"] = "instagram_handle_or_fallback"
        reply_text = str(resolved.get("message") or "What is your friend's Instagram @handle or post URL?")
        messages.append({
            "id": f"assistant-{uuid.uuid4().hex[:10]}",
            "role": "assistant",
            "text": reply_text,
            "created_at": now_iso(),
        })
        saved = db.save_conversation_session(session_id, user_id, state, messages)
        return {
            "session_id": session_id,
            "reply": reply_text,
            "state": saved["state"],
            "messages": saved["messages"],
            "history": history,
            "instagram_status": resolved.get("status"),
            "instagram_resolution": resolved,
        }

    # 4. Ask ONE useful question at a time
    if not state.get("product"):
        state["last_question_key"] = "product"
        reply_text = "What item are you looking to buy today—for example, a T-shirt, shirt, or travel outfit?"
        messages.append({"id": f"assistant-{uuid.uuid4().hex[:10]}", "role": "assistant", "text": reply_text, "created_at": now_iso()})
        saved = db.save_conversation_session(session_id, user_id, state, messages)
        return {"session_id": session_id, "reply": reply_text, "state": saved["state"], "messages": saved["messages"], "history": history}

    if state.get("budget") is None:
        state["last_question_key"] = "budget_and_size"
        if not state.get("size_confirmed"):
            state["size_prompted_value"] = usual_top_size
            reply_text = f"Do you have a budget in mind? Should I use your usual size {usual_top_size}?"
        else:
            reply_text = f"Do you have a budget in mind for the {state['product'].lower()}?"
        messages.append({"id": f"assistant-{uuid.uuid4().hex[:10]}", "role": "assistant", "text": reply_text, "created_at": now_iso()})
        saved = db.save_conversation_session(session_id, user_id, state, messages)
        return {"session_id": session_id, "reply": reply_text, "state": saved["state"], "messages": saved["messages"], "history": history}

    if not state.get("size_confirmed"):
        state["last_question_key"] = "size"
        state["size_prompted_value"] = usual_top_size
        conflict_info = (history.get("conflicts") or {}).get("top_size") or {}
        if conflict_info.get("has_conflict"):
            others = ", ".join(conflict_info.get("conflicting_values") or [])
            reply_text = f"Should I use your usual size {usual_top_size} (or {others} from recent orders)?"
        else:
            reply_text = f"Should I use your usual size {usual_top_size}?"
        messages.append({"id": f"assistant-{uuid.uuid4().hex[:10]}", "role": "assistant", "text": reply_text, "created_at": now_iso()})
        saved = db.save_conversation_session(session_id, user_id, state, messages)
        return {"session_id": session_id, "reply": reply_text, "state": saved["state"], "messages": saved["messages"], "history": history}

    # Check if user provided a direct style description in this turn
    if not state.get("style") and not state.get("reference_attributes"):
        if parsed_color or parsed_fit or re.search(r"\b(minimal|monotonic|casual|linen|printed|striped|solid|earthy|beach|retro|streetwear|no\s+reference|any\s+style)\b", clean_text.lower()):
            state["style"] = " ".join(filter(None, [parsed_fit, parsed_color, "casual"])).strip() or "relaxed coastal"
        elif not state.get("style_prompted"):
            state["style_prompted"] = True
            state["last_question_key"] = "style_or_reference"
            reply_text = "Do you have a style or reference in mind?"
            messages.append({"id": f"assistant-{uuid.uuid4().hex[:10]}", "role": "assistant", "text": reply_text, "created_at": now_iso()})
            saved = db.save_conversation_session(session_id, user_id, state, messages)
            return {"session_id": session_id, "reply": reply_text, "state": saved["state"], "messages": saved["messages"], "history": history}

    # 5. All needed constraints are collected -> run search and return products!
    return _execute_search_from_state(user_id, session_id, state, messages, history)


def confirm_instagram_post_and_search(
    user_id: str,
    *,
    session_id: str,
    reference_id: str,
    item_hint: str = "T-shirt",
) -> dict[str, Any]:
    """Confirm a captured/saved Instagram reference post and item, analyze it locally, and search retailers."""
    session = get_or_start_session(user_id, session_id=session_id)
    state: dict[str, Any] = dict(session["state"])
    messages: list[dict[str, Any]] = list(session["messages"])
    history = session["history"]

    if item_hint:
        state["product"] = item_hint
        state["category"] = item_hint

    record = db.get_instagram_reference(reference_id, user_id)
    if not record:
        raise ValueError("Instagram reference screenshot was not found.")

    messages.append({
        "id": f"user-{uuid.uuid4().hex[:10]}",
        "role": "user",
        "text": f"Confirmed reference post ({record.get('post_url')}) — match the {item_hint}.",
        "created_at": now_iso(),
    })

    analysis = analyze_clothing_reference(
        user_id,
        reference_id=reference_id,
        item_hint=item_hint,
        caption=record.get("caption") or "",
    )
    attrs = analysis["attributes"]
    state["selected_reference"] = {
        **record,
        "attributes": attrs,
        "confirmed": True,
        "screenshot_url": f"/api/social/screenshots/{record['id']}",
    }
    state["reference_attributes"] = attrs
    state["color"] = attrs.get("color") or state.get("color")
    state["fit"] = attrs.get("fit") or state.get("fit")
    state["fabric"] = attrs.get("fabric") or state.get("fabric")
    state["style"] = attrs.get("theme") or state.get("style")
    state["awaiting_post_confirmation"] = False
    state["awaiting_instagram_handle"] = False

    return _execute_search_from_state(user_id, session_id, state, messages, history)
