from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .settings import is_production, setting
from .usage import record_usage


ANAKIN_BASE_URL = setting("ANAKIN_BASE_URL", "https://api.anakin.io/v1").rstrip("/")
OLLAMA_BASE_URL = setting("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = setting("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_VISION_MODEL = setting("OLLAMA_VISION_MODEL", OLLAMA_MODEL)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    candidate = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Some local reasoning models prefix an otherwise valid fenced JSON object
        # with trace-like text. Decode from the final object boundary so that prefix
        # is never mistaken for user-visible structured data.
        decoder = json.JSONDecoder()
        parsed = None
        for start in reversed([match.start() for match in re.finditer(r"{", candidate)]):
            try:
                possible, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(possible, dict):
                parsed = possible
                break
        if parsed is None:
            return None
    return parsed if isinstance(parsed, dict) else None


class AnakinClient:
    """Anakin Search API and inline URL Scraper client. Credentials never leave the backend."""

    def __init__(self) -> None:
        self.api_key = setting("ANAKIN_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def search(self, query: str, num_results: int = 8) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Anakin is not configured")
        result = _request_json(
            f"{ANAKIN_BASE_URL}/search",
            method="POST",
            payload={"prompt": query, "limit": min(max(num_results, 1), 10), "region": "in", "language": "en"},
            headers=self._headers(),
            timeout=45,
        )
        record_usage("anakin", "live_search", model="search", input_characters=len(query))
        return result

    def scrape_inline(self, url: str) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Anakin is not configured")
        result = _request_json(
            f"{ANAKIN_BASE_URL}/url-scraper/scrape",
            method="POST",
            payload={"url": url, "country": "in", "useBrowser": True, "generateJson": True},
            headers=self._headers(),
            timeout=90,
        )
        job_id = result.get("id") if isinstance(result, dict) else None
        if result.get("status") == "processing" and job_id:
            for _ in range(20):
                time.sleep(1.5)
                result = _request_json(f"{ANAKIN_BASE_URL}/url-scraper/{job_id}", headers=self._headers(), timeout=30)
                if result.get("status") == "completed":
                    record_usage("anakin", "reference_scrape", model="url-scraper", input_characters=len(url))
                    return result
                if result.get("status") == "failed":
                    raise RuntimeError("Anakin could not extract that URL")
            raise TimeoutError("Anakin extraction timed out")
        if result.get("status") == "failed":
            raise RuntimeError("Anakin could not extract that URL")
        record_usage("anakin", "reference_scrape", model="url-scraper", input_characters=len(url))
        return result


class OllamaClient:
    def __init__(self) -> None:
        self.enabled = setting("OLLAMA_ENABLED", "1").lower() not in {"0", "false", "no"}
        self.model = OLLAMA_MODEL
        self.vision_model = OLLAMA_VISION_MODEL

    @property
    def configured(self) -> bool:
        return self.enabled

    def extract_brief(self, prompt: str, reference_image: dict[str, str] | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload: dict[str, Any] = {
            "model": self.vision_model if reference_image else self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        if reference_image:
            payload["images"] = [reference_image["data_base64"]]
            # Vision-capable local models can otherwise prepend private reasoning
            # traces to their JSON response. The purchase brief needs only the
            # structured result that is safe to persist and display.
            payload["think"] = False
        try:
            response = _request_json(
                f"{OLLAMA_BASE_URL}/api/generate",
                method="POST",
                payload=payload,
                timeout=35 if reference_image else 10,
            )
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
            return None
        input_tokens = response.get("prompt_eval_count")
        output_tokens = response.get("eval_count")
        total_tokens = response.get("total_tokens")
        record_usage(
            "ollama",
            "brief_extraction",
            model=payload["model"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        return _json_object(response.get("response"))


class GeminiClient:
    def __init__(self) -> None:
        self.api_key = setting("GEMINI_API_KEY")
        self.model = setting("GEMINI_MODEL", "gemini-2.5-flash")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def extract_brief(self, prompt: str, reference_image: dict[str, str] | None = None) -> dict[str, Any] | None:
        if not self.configured:
            return None
        model = urllib.parse.quote(self.model, safe="-._")
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if reference_image:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": reference_image["mime_type"],
                        "data": reference_image["data_base64"],
                    }
                }
            )
        try:
            response = _request_json(
                f"{GEMINI_BASE_URL}/models/{model}:generateContent",
                method="POST",
                payload={
                    "systemInstruction": {"parts": [{"text": "Return only a valid JSON object. Do not use markdown."}]},
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.15},
                },
                headers={"x-goog-api-key": self.api_key},
                timeout=35,
            )
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError):
            return None
        metadata = response.get("usageMetadata") or {}
        record_usage(
            "gemini",
            "brief_extraction",
            model=self.model,
            input_tokens=metadata.get("promptTokenCount"),
            output_tokens=metadata.get("candidatesTokenCount"),
            total_tokens=metadata.get("totalTokenCount"),
            cached_tokens=metadata.get("cachedContentTokenCount"),
        )
        candidates = response.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        return _json_object(text)


class BriefModel:
    """Deterministically selects local Ollama for development and Gemini for production."""

    def __init__(self) -> None:
        self.preference = setting("AI_PROVIDER", "auto").lower()
        self.ollama = OllamaClient()
        self.gemini = GeminiClient()

    @property
    def provider(self) -> str:
        if self.preference in {"ollama", "gemini"}:
            return self.preference
        return "gemini" if is_production() else "ollama"

    def status(self) -> dict[str, object]:
        active = self.provider
        configured = self.gemini.configured if active == "gemini" else self.ollama.configured
        model = self.gemini.model if active == "gemini" else self.ollama.model
        return {"provider": active, "model": model, "configured": configured, "gemini_configured": self.gemini.configured, "ollama_enabled": self.ollama.configured}

    def extract_brief(self, text: str, reference_image: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, str]:
        image_context = reference_image["name"] if reference_image else "none"
        prompt = f"""
You are the brief agent for a real purchase-assistant in India.
Extract shopping constraints from the user's request. Return JSON only with these keys:
category, occasion, budget, quantity, brand, location, pincode, color, size, fabric, arrive_by, arrive_by_days, must_have, specifications, nice_to_have, style, description.
Use null for unknown budget/location/date and arrays for must_have/nice_to_have.
Keep color, size, fabric, and pincode as first-class fields when the user states them. Do not infer a location from a phrase such as “in three days”.
User request: {text}
Reference image: {image_context}. If an image is attached, infer its product category, colours, silhouette, material cues, and style before extracting the brief.
""".strip()
        if self.provider == "gemini":
            return self.gemini.extract_brief(prompt, reference_image), "gemini"
        return self.ollama.extract_brief(prompt, reference_image), "ollama"


def parse_price(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(?:₹|INR|Rs\.?|रु\.?)[\s]*([\d,]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None
