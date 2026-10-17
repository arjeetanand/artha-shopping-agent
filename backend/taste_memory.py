"""User-scoped purchase and inspiration memory with real semantic embeddings."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from .clients import _request_json
from .db import db
from .settings import setting
from .usage import record_usage


def _valid_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not 32 <= len(value) <= 4096:
        raise ValueError("Embedding provider returned an invalid vector")
    vector = [float(number) for number in value]
    if not all(math.isfinite(number) for number in vector) or not any(vector):
        raise ValueError("Embedding provider returned an invalid vector")
    return vector


def embed_documents(texts: list[str], *, query: bool = False) -> tuple[list[list[float]], str]:
    provider = setting("TASTE_EMBEDDING_PROVIDER", "gemini" if setting("GEMINI_API_KEY") else "ollama")
    if provider == "gemini":
        key = setting("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Gemini embeddings are not configured")
        model = setting("TASTE_EMBEDDING_MODEL", "gemini-embedding-001")
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
            raise ValueError("Invalid embedding model")
        result = _request_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents",
            method="POST", headers={"x-goog-api-key": key}, timeout=20,
            payload={"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": text[:12000]}]},
                                    "taskType": "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
                                    "outputDimensionality": 768} for text in texts]},
        )
        vectors = [_valid_vector(item.get("values")) for item in result.get("embeddings", [])]
    elif provider == "ollama":
        model = setting("TASTE_EMBEDDING_MODEL", "nomic-embed-text")
        result = _request_json(setting("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/embed",
                               method="POST", payload={"model": model, "input": texts}, timeout=30)
        vectors = [_valid_vector(value) for value in result.get("embeddings", [])]
    else:
        raise ValueError("Unsupported embedding provider")
    if len(vectors) != len(texts):
        raise ValueError("Embedding provider did not return every vector")
    record_usage(provider, "taste_embedding", model=model, input_characters=sum(map(len, texts)))
    return vectors, f"{provider}:{model}"


def save_memories(user_id: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {item["source_key"]: item for item in db.list_taste_memories(user_id)}
    results = []
    for start in range(0, len(memories), 32):
        batch = memories[start:start + 32]
        pending = [item for item in batch if not (existing.get(item["source_key"], {}).get("embedding")
                   and existing[item["source_key"]]["document"] == item["document"])]
        vectors, model = [], ""
        if pending:
            try:
                vectors, model = embed_documents([item["document"] for item in pending])
            except (OSError, ValueError, RuntimeError):
                # shortcut: keep evidence if embeddings are unavailable; reindex after the provider is restored.
                pass
        computed = {item["source_key"]: vector for item, vector in zip(pending, vectors)}
        for item in batch:
            previous = existing.get(item["source_key"], {})
            same_document = previous.get("document") == item["document"]
            vector = computed.get(item["source_key"]) or (previous.get("embedding") if same_document else None)
            model_name = model if item["source_key"] in computed else previous.get("embedding_model", "") if same_document else ""
            results.append(db.save_taste_memory(user_id, item["source_key"], item["kind"], item["document"],
                           item.get("attributes", {}), item.get("source_url", ""), vector, model_name))
    return results


def remember_orders(user_id: str, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memories = []
    for order in orders:
        if order.get("data_source") != "retailer_session":
            continue
        for index, item in enumerate(order.get("items") or []):
            attributes = {key: item[key] for key in ("name", "brand", "category", "size", "color", "vibe", "price") if item.get(key) is not None}
            attributes.update({"order_id": order["id"], "provider": order["payment_provider"], "order_date": order.get("order_date")})
            document = ". ".join(str(item[key]) for key in ("name", "brand", "category", "size", "color", "vibe") if item.get(key))
            if document:
                memories.append({"source_key": f"purchase:{order['id']}:{index}", "kind": "purchase",
                                 "document": document[:8000], "attributes": attributes,
                                 "source_url": item.get("url") or order.get("source_url", "")})
    return save_memories(user_id, memories)


def remember_link(user_id: str, result: dict[str, Any]) -> dict[str, Any]:
    url = result["url"]
    attributes = {key: result.get(key) for key in ("theme", "colors", "style_tags", "summary", "analysis_source")}
    document = ". ".join(filter(None, [result.get("theme"), result.get("summary"),
                                      ", ".join(result.get("colors") or []), ", ".join(result.get("style_tags") or [])]))
    return save_memories(user_id, [{"source_key": "link:" + hashlib.sha256(url.encode()).hexdigest(),
                          "kind": "saved_link", "source_url": url, "document": document[:8000], "attributes": attributes}])[0]


def public_memories(user_id: str) -> list[dict[str, Any]]:
    return [{key: item[key] for key in ("id", "source_key", "kind", "source_url", "document", "attributes", "created_at", "updated_at")}
            | {"embedding_status": "ready" if item["embedding"] else "pending"}
            for item in db.list_taste_memories(user_id)]


def retrieve_memories(user_id: str, query: str, limit: int = 5) -> dict[str, Any]:
    memories = db.list_taste_memories(user_id)
    if not memories:
        return {"mode": "empty", "memories": []}
    query_vector, query_model = None, ""
    if any(item["embedding"] for item in memories):
        try:
            vectors, query_model = embed_documents([query], query=True)
            query_vector = vectors[0]
        except (OSError, ValueError, RuntimeError):
            pass
    query_words = set(re.findall(r"[a-z0-9]+", query.lower()))
    matches = []
    semantic_used = False
    for item in memories:
        words = set(re.findall(r"[a-z0-9]+", item["document"].lower()))
        lexical = len(words & query_words) / max(len(query_words), 1)
        cosine = 0.0
        vector = item["embedding"]
        if query_vector and vector and item["embedding_model"] == query_model and len(vector) == len(query_vector):
            denominator = math.sqrt(sum(v*v for v in vector) * sum(v*v for v in query_vector))
            cosine = sum(a*b for a,b in zip(vector,query_vector)) / denominator if denominator else 0
            semantic_used = True
        if lexical or cosine >= 0.45:
            matches.append({"id": item["id"], "kind": item["kind"], "document": item["document"],
                            "source_url": item["source_url"], "attributes": item["attributes"],
                            "relevance": round(0.75 * max(cosine, 0) + 0.25 * lexical, 4)})
    matches.sort(key=lambda item: item["relevance"], reverse=True)
    return {"mode": "hybrid" if semantic_used else "keyword", "memories": matches[:limit]}


def reindex_memories(user_id: str) -> list[dict[str, Any]]:
    return save_memories(user_id, db.list_taste_memories(user_id))
