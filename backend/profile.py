"""Shopping OS: User Taste Profile, Account Connection, and Knowledge/Vibe Graph Service."""
from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from .db import db, now_iso


def extract_taste_profile(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive brand loyalty, sizes, addresses, and vibe tags from completed orders."""
    brand_counts: Counter[str] = Counter()
    store_counts: Counter[str] = Counter()
    size_counts: dict[str, Counter[str]] = {"top": Counter(), "bottom": Counter(), "shoes": Counter()}
    vibe_counts: Counter[str] = Counter()
    colors: set[str] = set()
    addresses: list[dict[str, Any]] = []

    for order in orders:
        provider = str(order.get("payment_provider") or "").strip()
        if provider and provider not in {"sandbox", "fixture"}:
            store_counts[provider.title()] += 1
        items = order.get("items") or []
        payload = order.get("payload_json")
        if isinstance(payload, str):
            try:
                items = json.loads(payload).get("items") or items
            except Exception:
                pass

        for item in items:
            if not isinstance(item, dict):
                continue
            brand = str(item.get("brand") or "").strip()
            if brand and brand.lower() not in {"retailer", "store", "generic"}:
                brand_counts[brand] += 1

            size = str(item.get("size") or "").strip().upper()
            cat = str(item.get("category") or "").lower()
            if size:
                if any(k in cat for k in ("footwear", "shoe", "sneaker")):
                    size_counts["shoes"][size] += 1
                elif any(k in cat for k in ("bottom", "trouser", "pants", "jeans")):
                    size_counts["bottom"][size] += 1
                elif any(k in cat for k in ("clothing", "apparel", "shirt", "top")):
                    size_counts["top"][size] += 1

            vibe = str(item.get("vibe") or "").strip()
            if vibe:
                vibe_counts[vibe] += 1
            color = str(item.get("color") or "").strip().lower()
            if color:
                colors.add(color)

        location = str(order.get("location") or "")
        pincode = re.search(r"\b\d{6}\b", location)
        if pincode and not any(a["pincode"] == pincode.group() for a in addresses):
            city = location[:pincode.start()].strip(" ,")
            addresses.append({"id": f"addr-{pincode.group()}", "label": "Delivery", "city": city, "pincode": pincode.group(), "address_line": "", "is_default": not addresses})

    top_brands = [b for b, _ in brand_counts.most_common(6)]
    top_vibes = [v for v, _ in vibe_counts.most_common(4)]
    fav_stores = [s for s, _ in store_counts.most_common(4)]

    top_size = size_counts["top"].most_common(1)[0][0] if size_counts["top"] else ""
    shoe_size = size_counts["shoes"].most_common(1)[0][0] if size_counts["shoes"] else ""

    return {
        "brands": top_brands,
        "sizes": {
            "top": top_size,
            "bottom": size_counts["bottom"].most_common(1)[0][0] if size_counts["bottom"] else "",
            "shoes": shoe_size,
        },
        "vibes": top_vibes,
        "palette": sorted(colors),
        "addresses": addresses,
        "budget_bracket": {
            "apparel": {},
            "tech": {},
        },
        "favorite_stores": fav_stores,
        "summary": f"Brands: {', '.join(top_brands[:3])}. Sizes: {top_size or shoe_size or 'unknown'}." if orders else "No order history yet.",
    }


def refresh_profile(user_id: str) -> dict[str, Any]:
    orders = [order for order in db.list_orders(user_id) if order.get("data_source") in {"retailer_session", "gmail_receipt"}]
    preferences = extract_taste_profile(orders)
    memories = db.list_taste_memories(user_id)
    inspirations = [item for item in memories if item["kind"] != "purchase"]
    vibes = list(preferences["vibes"])
    palette = list(preferences["palette"])
    for memory in inspirations:
        attributes = memory["attributes"]
        for value in [attributes.get("theme"), *(attributes.get("style_tags") or [])]:
            if isinstance(value, str) and value.strip() and value not in vibes:
                vibes.append(value)
        for value in attributes.get("colors") or []:
            if isinstance(value, str) and value.strip() and value not in palette:
                palette.append(value)
    preferences["vibes"] = vibes[:12]
    preferences["palette"] = palette[:16]
    verified_orders = sum(order.get("data_source") == "retailer_session" for order in orders)
    email_orders = len(orders) - verified_orders
    preferences["summary"] = f"{verified_orders} verified retailer orders, {email_orders} orders from Gmail receipts, and {len(inspirations)} saved inspirations."
    connections = db.list_account_connections(user_id)
    stats = {"orders_tracked": len(orders), "gmail_orders": email_orders, "connected_accounts_count": sum(c["status"] in {"connected", "synced", "partial"} for c in connections),
             "context_depth_score": min(100, len(orders) * 4 + len(inspirations) * 4 + len(preferences["brands"]) * 2),
             "memories": len(memories), "vectors_ready": sum(bool(item["embedding"]) for item in memories),
             "invoices_downloaded": len(db.list_retailer_invoices(user_id)), "evidence_version": 1}
    saved = db.save_user_profile(user_id, preferences, stats)
    return {**saved, "connected_accounts": connections}


def get_or_create_profile(user_id: str) -> dict[str, Any]:
    record = db.get_user_profile(user_id)
    if not record or record.get("stats", {}).get("evidence_version") != 1:
        return refresh_profile(user_id)
    return {**record, "connected_accounts": db.list_account_connections(user_id)}


def ingest_retailer_orders(user_id: str, provider: str, orders: list[dict[str, Any]], cutoff: date) -> list[dict[str, Any]]:
    """Persist only dated order evidence returned by an authenticated retailer session."""
    if provider not in {"amazon", "flipkart", "myntra", "ajio"}:
        raise ValueError("Unsupported retailer")
    records = []
    for source in orders:
        order_date = date.fromisoformat(str(source.get("order_date") or ""))
        if not cutoff <= order_date <= date.today():
            continue
        retailer_id = str(source.get("id") or "").strip()
        if not retailer_id or len(retailer_id) > 160 or not source.get("evidence_hash"):
            raise ValueError("Retailer order evidence is missing")
        items = source.get("items")
        if not isinstance(items, list) or not items or any(not isinstance(item, dict) or not str(item.get("name") or "").strip() for item in items):
            raise ValueError("Retailer order has no readable items")
        total = source.get("total")
        if total is not None and (type(total) not in {int, float} or not math.isfinite(total) or total < 0):
            raise ValueError("Invalid retailer order total")
        record_id = "ret-" + hashlib.sha256(f"{user_id}:{provider}:{retailer_id}".encode()).hexdigest()[:32]
        record = {"id": record_id, "retailer_order_id": retailer_id, "user_id": user_id, "plan_id": None,
                  "status": source.get("status") or "unknown", "payment_status": "retailer_history",
                  "payment_provider": provider, "currency": "INR", "total": total if total is not None else 0,
                  "total_verified": total is not None, "items": items, "location": source.get("location") or "",
                  "order_date": order_date.isoformat(), "created_at": order_date.isoformat() + "T00:00:00Z",
                  "updated_at": now_iso(), "data_source": "retailer_session", "source_url": source.get("source_url", ""),
                  "evidence_hash": source["evidence_hash"], "invoice_status": source.get("invoice_status", "unavailable"),
                  "timeline": [{"key": "synced", "label": "Read from retailer account", "complete": True}],
                  "notice": "Read from your authenticated retailer order history."}
        db.save_order(record)
        records.append(record)
    return records


def ingest_gmail_orders(user_id: str, provider: str, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist dated retailer items parsed from a user's authenticated Gmail receipts."""
    if provider not in {"amazon", "flipkart", "myntra"}:
        raise ValueError("Unsupported Gmail retailer")
    existing_orders = {order.get("id"): order for order in db.list_orders(user_id)}
    records = []
    for source in orders:
        order_date = date.fromisoformat(str(source.get("order_date") or ""))
        if order_date > date.today():
            continue
        retailer_id = str(source.get("id") or "").strip()
        evidence_hash = str(source.get("evidence_hash") or "").strip()
        items = source.get("items")
        if not retailer_id or len(retailer_id) > 160 or not re.fullmatch(r"[a-f0-9]{64}", evidence_hash):
            raise ValueError("Gmail purchase evidence is missing")
        if not isinstance(items, list) or not items or any(not isinstance(item, dict) or not str(item.get("name") or "").strip() for item in items):
            raise ValueError("Gmail receipt has no readable products")
        normalized_items = []
        for item in items[:100]:
            name = str(item["name"]).strip()[:500]
            link = str(item.get("url") or "").strip()
            if link:
                from urllib.parse import urlsplit
                host = (urlsplit(link).hostname or "").lower()
                allowed = {"amazon.in", "amazon.com"} if provider == "amazon" else {"flipkart.com"} if provider == "flipkart" else {"myntra.com"}
                if urlsplit(link).scheme != "https" or not any(host == domain or host.endswith("." + domain) for domain in allowed):
                    link = ""
            price = item.get("price")
            if price is not None and (type(price) not in {int, float} or not math.isfinite(price) or price < 0):
                price = None
            normalized_items.append({"name": name, "url": link, "brand": str(item.get("brand") or "")[:160],
                                     "category": str(item.get("category") or "")[:100], "size": str(item.get("size") or "")[:60],
                                     "color": str(item.get("color") or "")[:80], "price": price, "quantity": 1})
        record_id = "ret-" + hashlib.sha256(f"{user_id}:{provider}:{retailer_id}".encode()).hexdigest()[:32]
        previous = existing_orders.get(record_id)
        if previous and previous.get("data_source") == "retailer_session":
            records.append(previous)
            continue
        if previous:
            seen = {(str(item.get("name", "")).casefold(), str(item.get("url", ""))) for item in previous.get("items", [])}
            normalized_items = (previous.get("items", []) + [item for item in normalized_items if (item["name"].casefold(), item["url"]) not in seen])[:100]
        record = {"id": record_id, "retailer_order_id": retailer_id, "user_id": user_id, "plan_id": None,
                  "status": str(source.get("status") or "unknown")[:80], "payment_status": "gmail_receipt",
                  "payment_provider": provider, "currency": "INR", "total": 0, "total_verified": False,
                  "items": normalized_items, "location": "", "order_date": order_date.isoformat(),
                  "created_at": order_date.isoformat() + "T00:00:00Z", "updated_at": now_iso(),
                  "data_source": "gmail_receipt", "source_url": "", "evidence_hash": evidence_hash,
                  "invoice_status": source.get("invoice_status", "unavailable"),
                  "timeline": [{"key": "synced", "label": "Parsed from a retailer email in Gmail", "complete": True}],
                  "notice": "Product details were parsed from an email receipt; confirm them with the original invoice."}
        db.save_order(record)
        existing_orders[record_id] = record
        records.append(record)
    return records


def build_context_graph(user_id: str, active_brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build a dynamic, interactive Knowledge Graph representing the shopper's Shopping OS.
    Nodes expand graphically as orders are synced, brands are preferred, and requirements are spoken.
    """
    profile = get_or_create_profile(user_id)
    preferences = profile.get("preferences") or {}
    stats = profile.get("stats") or {}
    connections = profile.get("connected_accounts") or []
    orders = [order for order in db.list_orders(user_id) if order.get("data_source") in {"retailer_session", "gmail_receipt"}]

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, label: str, group: str, color: str, size: int = 16, meta: dict[str, Any] | None = None):
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({
            "id": node_id,
            "label": label,
            "group": group,
            "color": color,
            "size": size,
            "meta": meta or {},
        })

    def add_link(source_id: str, target_id: str, label: str = "", strength: float = 1.0):
        if source_id not in seen_nodes or target_id not in seen_nodes:
            return
        links.append({
            "source": source_id,
            "target": target_id,
            "label": label,
            "strength": strength,
        })

    # Root Shopper Node
    root_id = "node-shopper-os"
    add_node(
        root_id,
        "Shopping OS",
        "root",
        "#1C3027",
        size=32,
        meta={"summary": preferences.get("summary"), "depth": stats.get("context_depth_score", 65)},
    )

    # 1. Retailer Hubs
    store_colors = {
        "amazon": "#B54708",
        "flipkart": "#2D5BD1",
        "ajio": "#A94F32",
        "myntra": "#C25E3E",
        "instagram": "#A94F32",
    }
    connected_providers = {c.get("provider", "").lower() for c in connections if c.get("status") in {"synced", "partial", "connected"}}
    for store, col in store_colors.items():
        is_conn = store in connected_providers
        node_id = f"store-{store}"
        add_node(
            node_id,
            store.title(),
            "store",
            col if is_conn else "#9EAFA2",
            size=22 if is_conn else 16,
            meta={"connected": is_conn, "provider": store},
        )
        add_link(root_id, node_id, "connected" if is_conn else "available", 1.2 if is_conn else 0.5)

    # 2. Vibe & Aesthetic Hubs
    for idx, vibe in enumerate(preferences.get("vibes", [])[:4]):
        vibe_id = f"vibe-{idx}"
        add_node(vibe_id, vibe, "vibe", "#A94F32", size=20, meta={"kind": "aesthetic"})
        add_link(root_id, vibe_id, "vibe preference", 1.0)

    # 3. Favorite Brands
    for idx, brand in enumerate(preferences.get("brands", [])[:6]):
        brand_id = f"brand-{idx}"
        add_node(brand_id, brand, "brand", "#287E5D", size=18, meta={"kind": "brand_affinity"})
        add_link(root_id, brand_id, "brand loyalty", 0.9)

    # 4. Sizing Matrix
    sizes = preferences.get("sizes", {})
    if sizes.get("top"):
        size_id = f"size-top-{sizes['top']}"
        add_node(size_id, f"Top: {sizes['top']}", "size", "#B54708", size=16, meta={"category": "top"})
        add_link(root_id, size_id, "preferred size", 0.8)
    if sizes.get("shoes"):
        size_id = f"size-shoes-{sizes['shoes']}"
        add_node(size_id, f"Shoes: {sizes['shoes']}", "size", "#B54708", size=16, meta={"category": "footwear"})
        add_link(root_id, size_id, "preferred shoe", 0.8)

    # 5. Delivery Hubs / Addresses
    for addr in preferences.get("addresses", []):
        addr_id = f"addr-{addr.get('id', addr.get('pincode'))}"
        lbl = f"📍 {addr.get('label')}: {addr.get('city')} ({addr.get('pincode')})"
        add_node(
            addr_id,
            lbl,
            "address",
            "#2D5BD1",
            size=18,
            meta={"default": addr.get("is_default", False), "pincode": addr.get("pincode")},
        )
        add_link(root_id, addr_id, "primary delivery hub" if addr.get("is_default") else "delivery hub", 1.1)

    # 6. Recent Orders
    for idx, order in enumerate(orders[:8]):
        ord_id = f"order-{order.get('id', idx)}"
        items = order.get("items") or []
        first_item = items[0] if items else {}
        name = first_item.get("name") or order.get("id")
        short_name = (name[:28] + "…") if len(name) > 30 else name
        price = order.get("total") or first_item.get("price") or 0
        prov = str(order.get("payment_provider") or "retailer").lower()

        add_node(
            ord_id,
            f"📦 {short_name}",
            "order",
            "#596159",
            size=14,
            meta={"price": f"₹{price:,}" if price else "Price not exposed by retailer", "status": order.get("status"), "provider": prov},
        )

        # Link to retailer store
        if f"store-{prov}" in seen_nodes:
            add_link(f"store-{prov}", ord_id, "fulfilled by", 0.8)
        else:
            add_link(root_id, ord_id, "order placed", 0.7)

        # Link to matching brand if applicable
        brand = first_item.get("brand")
        if brand:
            for b_idx, pref_brand in enumerate(preferences.get("brands", [])):
                if brand.lower() in pref_brand.lower():
                    add_link(f"brand-{b_idx}", ord_id, "purchased item", 0.6)
                    break

    memories = db.list_taste_memories(user_id)
    for memory in memories[:80]:
        attributes = memory["attributes"]
        label = str(attributes.get("name") or attributes.get("theme") or memory["document"])[:45]
        add_node(memory["id"], label, "memory", "#287E5D", 16,
                 {"summary": memory["document"], "source_url": memory["source_url"], "kind": memory["kind"],
                  "embedding_status": "ready" if memory["embedding"] else "pending"})
        order_node = "order-" + str(attributes.get("order_id") or "")
        add_link(order_node if order_node in seen_nodes else root_id,memory["id"],"purchase evidence" if memory["kind"] == "purchase" else "saved inspiration",0.8)
        for idx,vibe in enumerate(preferences.get("vibes",[])[:4]):
            if vibe in [attributes.get("theme"), *(attributes.get("style_tags") or [])]:
                add_link(memory["id"],f"vibe-{idx}","observed style",0.6)

    invoices = db.list_retailer_invoices(user_id)
    by_retailer_id = {order.get("retailer_order_id"): "order-"+order["id"] for order in orders[:8]}
    for invoice in invoices[:30]:
        add_node(invoice["id"],f"Invoice {invoice['retailer_order_id']}","invoice","#B54708",13,
                 {"provider":invoice["provider"],"invoice_id":invoice["id"]})
        order_node = by_retailer_id.get(invoice["retailer_order_id"])
        add_link(order_node if order_node in seen_nodes else root_id,invoice["id"],"original invoice",0.6)

    # Active search connects only to the memories that retrieval actually used.
    if active_brief and active_brief.get("raw_text"):
        search_id = "node-active-search"
        clean_q = (active_brief.get("raw_text")[:32] + "…") if len(active_brief.get("raw_text", "")) > 34 else active_brief.get("raw_text")
        add_node(
            search_id,
            f"🔍 Active: {clean_q}",
            "search",
            "#A94F32",
            size=24,
            meta={"query": active_brief.get("raw_text"), "category": active_brief.get("category")},
        )
        add_link(root_id, search_id, "active research mission", 1.5)
        for memory in (active_brief.get("taste_context") or {}).get("memories",[]):
            add_link(search_id,memory["id"],"retrieved preference",1.2)

        # Connect active search to matching size / color / vibe nodes
        if active_brief.get("style"):
            for v_idx, v in enumerate(preferences.get("vibes", [])):
                if active_brief["style"].lower() in v.lower():
                    add_link(search_id, f"vibe-{v_idx}", "theme match", 1.2)
        if active_brief.get("location"):
            for addr in preferences.get("addresses", []):
                if active_brief["location"].lower() in addr.get("city", "").lower():
                    add_link(search_id, f"addr-{addr.get('id', addr.get('pincode'))}", "delivery match", 1.2)

    context_score = min(200, len(nodes) * 8 + len(links) * 4)

    return {
        "nodes": nodes,
        "links": links,
        "metrics": {
            "total_nodes": len(nodes),
            "total_edges": len(links),
            "context_score": context_score,
            "connected_accounts": len(connected_providers),
            "tracked_orders": len(orders),
            "favorite_brands": len(preferences.get("brands", [])),
            "saved_memories": len(memories),
            "vectors_ready": sum(bool(memory["embedding"]) for memory in memories),
            "invoices": len(invoices),
        },
        "summary": preferences.get("summary", ""),
    }

