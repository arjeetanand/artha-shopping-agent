from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import is_production, setting
from .usage import record_usage


ANAKIN_BASE_URL = setting("ANAKIN_BASE_URL", "https://api.anakin.io/v1").rstrip("/")
OLLAMA_BASE_URL = setting("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = setting("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_VISION_MODEL = setting("OLLAMA_VISION_MODEL", OLLAMA_MODEL)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_FREE_RETAILER_SCRIPT = Path(__file__).parent / "free_retailer_scraper.mjs"


def _node_bin() -> str:
    found = shutil.which("node")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "node"


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


class LocalRetailerClient:
    """Free, open-source local Playwright + JSON-LD/DOM scraper for Amazon India and Flipkart."""

    name = "local_playwright"

    @property
    def configured(self) -> bool:
        return True

    def _http_fallback_search(self, query: str, num_results: int = 8) -> dict[str, Any]:
        """Direct HTTP + HTML parser fallback for Amazon.in and Flipkart when Playwright is unavailable."""
        cleaned = re.sub(r"\bsite:[^\s]+|\bOR\b", " ", query, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        retrieved_at = datetime.now(timezone.utc).isoformat()
        results: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        # 1. Amazon India
        amz_url = f"https://www.amazon.in/s?k={urllib.parse.quote_plus(cleaned)}"
        try:
            req = urllib.request.Request(amz_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read(1_500_000).decode("utf-8", errors="ignore")
            if re.search(r"validateCaptcha|api-services-support@amazon", html, flags=re.IGNORECASE):
                diagnostics.append({"retailer": "Amazon India", "status": "bot_challenge", "retrieved_at": retrieved_at})
            else:
                cards = re.findall(
                    r'data-asin="([A-Z0-9]{10})"[\s\S]{1,4500}?<img[^>]+src="(https://m\.media-amazon\.com/images/[^"]+)"[^>]+alt="([^"]{6,240})"[\s\S]{1,2500}?<span class="a-offscreen">(₹[\d,]+)</span>',
                    html,
                )
                for asin, img, title, price_text in cards[: max(1, num_results // 2)]:
                    results.append({
                        "title": title.replace("&amp;", "&").replace("&#39;", "'").strip(),
                        "url": f"https://www.amazon.in/dp/{asin}",
                        "image": img,
                        "price_text": price_text,
                        "seller": "Amazon India",
                        "retrieved_at": retrieved_at,
                        "snippet": f"Price {price_text} · Observed on Amazon India at {retrieved_at}",
                        "data": {
                            "name": title.replace("&amp;", "&").strip(),
                            "price": price_text,
                            "currency": "INR",
                            "image": img,
                            "seller": "Amazon India",
                            "pageType": "productDetail",
                            "retrieved_at": retrieved_at,
                        },
                    })
                diagnostics.append({"retailer": "Amazon India", "status": "ok" if cards else "empty_or_layout_changed", "count": len(cards), "retrieved_at": retrieved_at})
        except Exception as exc:
            diagnostics.append({"retailer": "Amazon India", "status": "unavailable", "detail": str(exc)[:160], "retrieved_at": retrieved_at})

        # 2. Flipkart
        fk_url = f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(cleaned)}"
        try:
            req = urllib.request.Request(fk_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read(1_500_000).decode("utf-8", errors="ignore")
            matches = re.findall(
                r'href="(/[^"?#]+/p/itm[a-zA-Z0-9]+)[^"]*"[\s\S]{1,2500}?(₹[\d,]+)',
                html,
            )
            seen_fk: set[str] = set()
            for path, price_text in matches:
                full_url = f"https://www.flipkart.com{path}"
                if full_url in seen_fk:
                    continue
                seen_fk.add(full_url)
                slug = path.strip("/").split("/")[0].replace("-", " ").title()
                if len(slug) < 5:
                    continue
                results.append({
                    "title": slug,
                    "url": full_url,
                    "image": "",
                    "price_text": price_text,
                    "seller": "Flipkart",
                    "retrieved_at": retrieved_at,
                    "snippet": f"Price {price_text} · Observed on Flipkart at {retrieved_at}",
                    "data": {
                        "name": slug,
                        "price": price_text,
                        "currency": "INR",
                        "seller": "Flipkart",
                        "pageType": "productDetail",
                        "retrieved_at": retrieved_at,
                    },
                })
                if len(seen_fk) >= max(1, num_results // 2):
                    break
            diagnostics.append({"retailer": "Flipkart", "status": "ok" if seen_fk else "empty_or_layout_changed", "count": len(seen_fk), "retrieved_at": retrieved_at})
        except Exception as exc:
            diagnostics.append({"retailer": "Flipkart", "status": "unavailable", "detail": str(exc)[:160], "retrieved_at": retrieved_at})

        return {"results": results[:num_results], "diagnostics": diagnostics, "retrieved_at": retrieved_at}

    def search(self, query: str, num_results: int = 8) -> dict[str, Any]:
        limit = min(max(num_results, 1), 10)
        try:
            proc = subprocess.run(
                [_node_bin(), str(_FREE_RETAILER_SCRIPT), "search", query, str(limit)],
                capture_output=True,
                text=True,
                timeout=38,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parsed = json.loads(proc.stdout.strip())
                if isinstance(parsed, dict) and parsed.get("success") and isinstance(parsed.get("results"), list):
                    normalized = []
                    for item in parsed["results"]:
                        if not isinstance(item, dict):
                            continue
                        normalized.append({
                            **item,
                            "data": {
                                "name": item.get("title"),
                                "price": item.get("price_text"),
                                "currency": "INR" if item.get("price_text") else None,
                                "image": item.get("image"),
                                "seller": item.get("seller"),
                                "pageType": "productDetail",
                                "retrieved_at": item.get("retrieved_at") or parsed.get("retrieved_at"),
                            },
                        })
                    record_usage("local_playwright", "live_search", model="chromium-retailer-scraper", input_characters=len(query))
                    if normalized:
                        return {
                            "results": normalized,
                            "diagnostics": parsed.get("diagnostics") or [],
                            "retrieved_at": parsed.get("retrieved_at"),
                        }
        except Exception:
            pass
        fallback = self._http_fallback_search(query, num_results=limit)
        record_usage("local_playwright", "live_search_http_fallback", model="urllib-retailer-scraper", input_characters=len(query))
        return fallback

    def scrape_inline(self, url: str, max_wait_seconds: int = 45) -> dict[str, Any]:
        from .social import _public_reference_url, capture_social_page

        url, _ = _public_reference_url(url)
        try:
            proc = subprocess.run(
                [_node_bin(), str(_FREE_RETAILER_SCRIPT), "product", url],
                capture_output=True,
                text=True,
                timeout=min(25, max_wait_seconds),
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parsed = json.loads(proc.stdout.strip())
                if isinstance(parsed, dict) and parsed.get("success"):
                    record_usage("local_playwright", "product_scrape", model="chromium-retailer-scraper", input_characters=len(url))
                    return parsed
        except Exception:
            pass

        local = capture_social_page(url, product=True, timeout=min(25, max_wait_seconds))
        if local.get("success") and local.get("html"):
            return {
                "html": local["html"],
                "finalUrl": local.get("finalUrl") or url,
                "pageTitle": local.get("title") or "",
                "description": local.get("description") or "",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        raise RuntimeError("Local retailer scraper could not verify that product page.")


class AnakinClient:
    """Anakin Search API and inline URL Scraper client. Credentials never leave the backend."""

    name = "anakin"

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

    def scrape_inline(self, url: str, max_wait_seconds: int = 90) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Anakin is not configured")
        deadline = time.monotonic() + max_wait_seconds
        result = _request_json(
            f"{ANAKIN_BASE_URL}/url-scraper/scrape",
            method="POST",
            payload={"url": url, "country": "in", "useBrowser": True, "generateJson": True},
            headers=self._headers(),
            timeout=max_wait_seconds,
        )
        job_id = result.get("id") if isinstance(result, dict) else None
        if result.get("status") == "processing" and job_id:
            for _ in range(20):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.5, remaining))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                result = _request_json(f"{ANAKIN_BASE_URL}/url-scraper/{job_id}", headers=self._headers(), timeout=max(1, min(30, int(remaining))))
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


class TavilyClient:
    """Basic-tier discovery with free local product-page checks."""

    name = "tavily"

    def __init__(self) -> None:
        self.api_key = setting("TAVILY_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, endpoint: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Tavily is not configured. Add TAVILY_API_KEY to .env and restart the API.")
        result = _request_json(
            f"https://api.tavily.com/{endpoint}", method="POST", payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"}, timeout=timeout,
        )
        if not isinstance(result, dict):
            raise RuntimeError("Tavily returned an invalid response")
        record_usage("tavily", endpoint, model="basic", input_characters=len(str(payload.get("query") or payload.get("urls") or "")))
        return result

    def search(self, query: str, num_results: int = 8) -> dict[str, Any]:
        domains = [domain.split("/", 1)[0] for domain in re.findall(r"\bsite:([^\s]+)", query)]
        if domains:
            query = re.sub(r"\s+", " ", re.sub(r"\bsite:[^\s]+|\bOR\b", "", query)).strip()
        response = self._request("search", {
            "query": query, "max_results": min(max(num_results, 1), 10),
            "search_depth": "basic", "auto_parameters": False,
            "country": "india", "include_answer": False, "include_raw_content": False,
            **({"include_domains": domains} if domains else {}),
        })
        results = response.get("results")
        if not isinstance(results, list):
            raise RuntimeError("Tavily returned invalid search results")
        return {"results": [{**item, "snippet": item.get("content") or ""} for item in results if isinstance(item, dict)]}

    def scrape_inline(self, url: str, max_wait_seconds: int = 90) -> dict[str, Any]:
        from .social import _public_reference_url, capture_social_page

        url, _ = _public_reference_url(url)
        started = time.monotonic()
        local = capture_social_page(url, product=True, timeout=min(30, max_wait_seconds))
        if local.get("success") and local.get("html"):
            return {"html": local["html"], "finalUrl": local.get("finalUrl") or url,
                    "pageTitle": local.get("title") or "", "description": local.get("description") or ""}
        remaining = int(max_wait_seconds - (time.monotonic() - started))
        if remaining < 1:
            raise TimeoutError("Product page extraction timed out")
        response = self._request("extract", {
            "urls": [url], "extract_depth": "basic", "format": "markdown",
            "timeout": min(10, remaining),
        }, timeout=remaining)
        results = response.get("results") or []
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict) or not results[0].get("raw_content"):
            raise RuntimeError("Tavily could not extract that URL")
        # Text is reference context only; purchase claims require retailer JSON-LD.
        return {"markdown": results[0]["raw_content"], "finalUrl": results[0].get("url") or url}


def get_search_client() -> AnakinClient | TavilyClient | LocalRetailerClient:
    provider = setting("SHOPPINGHELP_SEARCH_PROVIDER", "auto").lower()
    if provider in {"local", "playwright", "free", "local_playwright"}:
        return LocalRetailerClient()
    if provider == "auto":
        if setting("TAVILY_API_KEY"):
            return TavilyClient()
        if setting("ANAKIN_API_KEY"):
            return AnakinClient()
        return LocalRetailerClient()
    if provider not in {"anakin", "tavily"}:
        raise ValueError("SHOPPINGHELP_SEARCH_PROVIDER must be auto, local, tavily, or anakin")
    return TavilyClient() if provider == "tavily" else AnakinClient()


def search_status() -> dict[str, Any]:
    client = get_search_client()
    return {
        "search_provider": client.name,
        "search_configured": client.configured,
        "supported_retailers": ["Amazon India (amazon.in)", "Flipkart (flipkart.com)", "Myntra (myntra.com)", "AJIO (ajio.com)"],
    }


def search_failure(provider: str, error: Exception) -> str:
    label = "Local Playwright Scraper" if provider == "local_playwright" else provider.title()
    code = getattr(error, "code", None)
    if code in {402, 432, 433}:
        return f"{label} search credits are exhausted (HTTP {code}). Check your provider balance or switch SHOPPINGHELP_SEARCH_PROVIDER=local."
    if code in {401, 403}:
        return f"{label} rejected the API key (HTTP {code}). Check {provider.upper()}_API_KEY and account access."
    if code == 429:
        return f"{label} search rate limit reached. Wait before trying again."
    return f"{label} live search failed{f' (HTTP {code})' if code else ''}. Check provider availability and network access."


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
        return {
            "provider": active,
            "model": model,
            "vision_model": self.ollama.vision_model if active == "ollama" else self.gemini.model,
            "configured": configured,
            "gemini_configured": self.gemini.configured,
            "ollama_enabled": self.ollama.configured,
        }

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
