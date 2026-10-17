"""Read retailer receipts from Gmail and feed their products into Shopping OS."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .auth import GOOGLE_TOKEN_URL, _post_form_json
from .connections import _store_invoice, private_root, provider_directory
from .db import db, now_iso
from .profile import ingest_gmail_orders, refresh_profile
from .settings import setting
from .taste_memory import remember_orders


GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SEARCH = "{from:amazon.in from:amazon.com from:flipkart.com from:myntra.com}"
_MAX_PDF_BYTES = 20 * 1024 * 1024
_MAX_MESSAGE_TEXT_BYTES = 1_000_000
_TRANSACTION_RE = re.compile(r"\b(order|invoice|receipt|shipped|shipment|delivered|dispatch|refund|return|purchase|placed|confirmed)\b", re.I)
_ORDER_ID_RE = re.compile(r"\b(?:OD\d{8,}|\d{3}-\d{7}-\d{7}|(?:order|invoice|transaction)\s*(?:id|no\.?|number)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9-]{3,})\b", re.I)
_LABELLED_ITEM_RE = re.compile(r"^(?:product|item|description)\s*[:\-]\s*(.{5,200})$", re.I)
_QUANTITY_ITEM_RE = re.compile(r"^(.{8,200}?)\s+(?:qty|quantity)\s*[:x]?\s*\d+\b", re.I)
_ACTIVE = {"syncing", "indexing"}
_LOCK = threading.RLock()
_JOBS: dict[str, dict[str, Any]] = {}

_RETAILERS = {
    "amazon": {"amazon.in", "amazon.com"},
    "flipkart": {"flipkart.com"},
    "myntra": {"myntra.com"},
}


class GmailSyncError(RuntimeError):
    def __init__(self, message: str, *, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


class _HtmlContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href") or ""
            self._anchor = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text.append(value)
            if self._href is not None:
                self._anchor.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((" ".join(self._anchor), self._href))
            self._href = None
            self._anchor = []


def _token_key() -> bytes:
    secret = setting("GOOGLE_CLIENT_SECRET")
    if not secret:
        raise GmailSyncError("Google OAuth is not configured on this server.", fatal=True)
    # shortcut: the encryption key follows GOOGLE_CLIENT_SECRET; reconnect Gmail after rotating that secret.
    return hmac.new(secret.encode("utf-8"), b"artha:gmail-refresh-token:v1", hashlib.sha256).digest()


def encrypt_refresh_token(user_id: str, token: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_token_key()).encrypt(nonce, token.encode("utf-8"), user_id.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def _decrypt_refresh_token(user_id: str, ciphertext: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        return AESGCM(_token_key()).decrypt(payload[:12], payload[12:], user_id.encode("utf-8")).decode("utf-8")
    except Exception as error:
        raise GmailSyncError("Gmail access could not be unlocked. Reconnect Gmail to continue.", fatal=True) from error


def save_gmail_connection(user_id: str, email: str, refresh_token: str) -> dict[str, Any]:
    db.save_gmail_token(user_id, email, encrypt_refresh_token(user_id, refresh_token))
    return db.save_account_connection(user_id, "gmail", email, status="connected", details={"message": "Gmail is connected. Its retailer order and invoice emails are ready to sync."})


def _access_token(user_id: str) -> str:
    stored = db.get_gmail_token(user_id)
    if not stored:
        raise GmailSyncError("Connect Gmail before starting a sync.", fatal=True)
    refresh_token = _decrypt_refresh_token(user_id, stored["refresh_token_ciphertext"])
    client_id, client_secret = setting("GOOGLE_CLIENT_ID"), setting("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GmailSyncError("Google OAuth is not configured on this server.", fatal=True)
    try:
        tokens = _post_form_json(GOOGLE_TOKEN_URL, {"client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"})
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as error:
        raise GmailSyncError("Google could not refresh Gmail access. Reconnect Gmail and try again.", fatal=True) from error
    token = str(tokens.get("access_token") or "")
    if not token:
        raise GmailSyncError("Google did not issue a Gmail access token. Reconnect Gmail and try again.", fatal=True)
    return token


def _google_get(path: str, access_token: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{GMAIL_API_ROOT}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(30 * 1024 * 1024 + 1)
            if len(raw) > 30 * 1024 * 1024:
                raise GmailSyncError("Gmail returned an oversized message.")
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise GmailSyncError("Gmail access expired or was revoked. Reconnect Gmail to continue.", fatal=True) from error
            if error.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            if error.code == 403:
                raise GmailSyncError("Gmail API access was denied. Check that the Gmail API is enabled and read-only access is approved.", fatal=True) from error
            raise GmailSyncError(f"Gmail API request failed (HTTP {error.code}).") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise GmailSyncError("Gmail API could not be reached. Try the sync again.") from error
    raise GmailSyncError("Gmail API could not complete the request.")


def _decode_data(value: str, limit: int) -> bytes:
    if len(value) > limit * 2:
        raise ValueError("Email part exceeds the supported size")
    if not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", value):
        raise ValueError("Email part has invalid base64 data")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(decoded) > limit:
        raise ValueError("Email part exceeds the supported size")
    return decoded


def _header(message: dict[str, Any], key: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    for item in headers:
        if str(item.get("name") or "").lower() == key.lower():
            try:
                return str(make_header(decode_header(str(item.get("value") or ""))))
            except (LookupError, UnicodeError, ValueError):
                return str(item.get("value") or "")
    return ""


def _provider(message: dict[str, Any]) -> str:
    sender = parseaddr(_header(message, "From"))[1].lower()
    if "@" not in sender:
        return ""
    host = sender.rsplit("@", 1)[-1]
    for name, domains in _RETAILERS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return name
    return ""


def _message_date(message: dict[str, Any]) -> str:
    try:
        return datetime.fromtimestamp(int(message.get("internalDate")) / 1000, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        try:
            parsed = parsedate_to_datetime(_header(message, "Date"))
            return parsed.date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return ""


def _parts(message: dict[str, Any], message_id: str, access_token: str) -> tuple[str, list[tuple[str, str]], list[tuple[str, bytes]]]:
    plain: list[str] = []
    html_parts: list[str] = []
    attachments: list[tuple[str, bytes]] = []

    def visit(part: dict[str, Any]) -> None:
        body = part.get("body") if isinstance(part.get("body"), dict) else {}
        filename = str(part.get("filename") or "")[:240]
        mime = str(part.get("mimeType") or "").lower()
        attachment_id = str(body.get("attachmentId") or "")
        if filename.lower().endswith(".pdf") or mime == "application/pdf":
            if attachment_id:
                data = _google_get(f"messages/{urllib.parse.quote(message_id, safe='')}/attachments/{urllib.parse.quote(attachment_id, safe='')}", access_token).get("data")
            else:
                data = body.get("data")
            if isinstance(data, str):
                attachments.append((filename or "invoice.pdf", _decode_data(data, _MAX_PDF_BYTES)))
        elif mime in {"text/plain", "text/html"} and isinstance(body.get("data"), str):
            text = _decode_data(body["data"], _MAX_MESSAGE_TEXT_BYTES).decode("utf-8", errors="replace")
            (plain if mime == "text/plain" else html_parts).append(text)
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                visit(child)

    payload = message.get("payload")
    if isinstance(payload, dict):
        visit(payload)
    texts = "\n".join(plain + html_parts)
    links: list[tuple[str, str]] = []
    if html_parts:
        parser = _HtmlContent()
        parser.feed("\n".join(html_parts))
        links = parser.links
        texts += "\n" + "\n".join(parser.text)
    return texts[:_MAX_MESSAGE_TEXT_BYTES], links, attachments


def _clean_product_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|·•-:")[:500]


def _is_action_link(name: str) -> bool:
    return bool(re.search(r"\b(view|track|cancel|manage|download|invoice|order details|see more|shop now|return|help|support)\b", name, re.I))


def _product_link(provider: str, url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or not any(host == domain or host.endswith("." + domain) for domain in _RETAILERS[provider]):
        return False
    return any(token in path for token in ("/dp/", "/gp/product/", "/product/", "/p/", "/buy/"))


def _items_from_links(provider: str, links: list[tuple[str, str]]) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for label, url in links:
        name = _clean_product_text(label)
        if len(name) < 6 or _is_action_link(name) or not _product_link(provider, url):
            continue
        key = (name.casefold(), url)
        if key not in seen:
            items.append({"name": name, "url": url})
            seen.add(key)
    return items[:100]


def _items_from_text(text: str) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for line in text.splitlines():
        candidate = _LABELLED_ITEM_RE.match(line.strip()) or _QUANTITY_ITEM_RE.match(line.strip())
        if not candidate:
            continue
        name = _clean_product_text(candidate.group(1))
        if len(name) < 6 or _is_action_link(name) or re.search(r"\b(invoice|order id|tax|gst|amount|shipping|address|payment|total)\b", name, re.I):
            continue
        if name.casefold() not in seen:
            items.append({"name": name, "url": ""})
            seen.add(name.casefold())
    return items[:100]


def _order_id(text: str, message_id: str) -> str:
    match = _ORDER_ID_RE.search(text)
    if match:
        value = match.group(0)
        labelled = re.search(r"\b(?:order|invoice|transaction)\s*(?:id|no\.?|number)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", value, re.I)
        return (labelled.group(1) if labelled else value).strip()[:160]
    return "gmail-" + hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]


def _invoice_text(user_id: str, provider: str, order_id: str, filename: str, content: bytes) -> str:
    directory = provider_directory(user_id, provider)
    invoice_dir = directory / "invoices"
    invoice_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in (private_root(), directory.parent, directory, invoice_dir):
        path.chmod(0o700)
    digest = hashlib.sha256(content).hexdigest()
    path = invoice_dir / f"{digest}.pdf"
    if not path.exists():
        with path.open("xb") as target:
            target.write(content)
    path.chmod(0o600)
    return _store_invoice(user_id, provider, {"filename": path.name, "sha256": digest, "retailer_order_id": order_id}, directory)


def _persist(job: dict[str, Any], status: str | None = None) -> None:
    if status:
        job["status"] = status
    snapshot = {key: value for key, value in job.items() if key not in {"user_id", "thread"}}
    db.save_account_connection(job["user_id"], "gmail", job["email"], job.get("orders", 0), job["status"], details=snapshot)


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"user_id", "thread"}}


def start_gmail_sync(user_id: str) -> dict[str, Any]:
    stored = db.get_gmail_token(user_id)
    if not stored:
        raise GmailSyncError("Connect Gmail before starting a sync.")
    with _LOCK:
        existing = _JOBS.get(user_id)
        if existing and existing["status"] in _ACTIVE:
            return _snapshot(existing)
        job = {"id": "gmail-" + hashlib.sha256(f"{user_id}:{time.time_ns()}".encode()).hexdigest()[:20],
               "user_id": user_id, "email": stored["account_email"], "status": "syncing",
               "message": "Searching Amazon, Flipkart, and Myntra emails in Gmail.", "messages_scanned": 0,
               "orders": 0, "invoices": 0, "skipped": 0, "errors": 0, "started_at": now_iso()}
        _JOBS[user_id] = job
        _persist(job)
        job["thread"] = threading.Thread(target=_run_sync, args=(job,), daemon=True, name="gmail-receipt-sync")
        job["thread"].start()
        return _snapshot(job)


def gmail_status(user_id: str) -> dict[str, Any] | None:
    connection = next((record for record in db.list_account_connections(user_id) if record["provider"] == "gmail"), None)
    if not connection:
        return None
    with _LOCK:
        job = _JOBS.get(user_id)
        if job:
            return {**connection, "status": job["status"], "synced_orders_count": job.get("orders", 0),
                    "details": {**connection.get("details", {}), **_snapshot(job)}}
    if connection["status"] in _ACTIVE:
        connection["status"] = "interrupted"
        connection["details"] = {**connection.get("details", {}), "message": "The app restarted before Gmail sync finished. Start sync again to continue."}
    return connection


def cancel_gmail_sync(user_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(user_id)
        if not job or job["status"] not in _ACTIVE:
            return gmail_status(user_id)
        job["status"] = "cancelled"
        job["message"] = "Gmail sync cancelled. Products and invoices already imported are kept."
        _persist(job)
        return _snapshot(job)


def _save_attachments(user_id: str, provider: str, order_id: str, attachments: list[tuple[str, bytes]]) -> list[str]:
    texts = []
    for filename, content in attachments:
        if len(content) > _MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
            raise ValueError("Gmail attachment is not a supported PDF")
        texts.append(_invoice_text(user_id, provider, order_id, filename, content))
    return texts


def _process_message(user_id: str, message_id: str, access_token: str) -> tuple[str, str, list[dict[str, Any]]]:
    message = _google_get(f"messages/{urllib.parse.quote(message_id, safe='')}", access_token, {"format": "full"})
    provider = _provider(message)
    if not provider:
        return "skipped", "", []
    subject = _header(message, "Subject")
    text, links, attachments = _parts(message, message_id, access_token)
    if not attachments and not _TRANSACTION_RE.search(subject + "\n" + text):
        return "skipped", provider, []
    date_value = _message_date(message)
    if not date_value:
        return "unreadable", provider, []
    order_id = _order_id(subject + "\n" + text, message_id)
    pdf_text = _save_attachments(user_id, provider, order_id, attachments)
    items = _items_from_links(provider, links)
    if not items:
        items = _items_from_text(text + "\n" + "\n".join(pdf_text))
    orders = []
    if items:
        evidence = hashlib.sha256(f"gmail:{message_id}:{provider}".encode("utf-8")).hexdigest()
        orders = ingest_gmail_orders(user_id, provider, [{"id": order_id, "order_date": date_value,
            "items": items, "evidence_hash": evidence, "invoice_status": "available" if attachments else "unavailable"}])
    result = "imported" if orders and attachments else "order_only" if orders else "invoice_only" if attachments else "unreadable"
    return result, provider, orders


def _run_sync(job: dict[str, Any]) -> None:
    user_id = job["user_id"]
    try:
        access_token = _access_token(user_id)
        page_token = ""
        imported_orders: dict[str, dict[str, Any]] = {}
        while True:
            if job["status"] == "cancelled":
                break
            params = {"q": GMAIL_SEARCH, "maxResults": "500"}
            if page_token:
                params["pageToken"] = page_token
            page = _google_get("messages", access_token, params)
            for item in page.get("messages") or []:
                if job["status"] == "cancelled":
                    break
                message_id = str(item.get("id") or "")
                if not message_id or len(message_id) > 256:
                    job["errors"] += 1
                    continue
                if db.has_gmail_import(user_id, message_id):
                    job["skipped"] += 1
                    continue
                try:
                    result, provider, orders = _process_message(user_id, message_id, access_token)
                    db.save_gmail_import(user_id, message_id, provider, result)
                    job["messages_scanned"] += 1
                    if result in {"imported", "order_only"}:
                        for order in orders:
                            imported_orders[order["id"]] = order
                    if result in {"imported", "invoice_only"}:
                        job["invoices"] += 1
                    if result in {"order_only", "imported"}:
                        job["orders"] += len(orders)
                    if result == "unreadable":
                        job["errors"] += 1
                except GmailSyncError:
                    raise
                except Exception:
                    job["errors"] += 1
                if job["messages_scanned"] % 25 == 0:
                    job["message"] = f"Checked {job['messages_scanned']} retailer emails, imported {job['orders']} orders and {job['invoices']} invoices."
                    _persist(job)
            page_token = str(page.get("nextPageToken") or "")
            if not page_token or job["status"] == "cancelled":
                break
        remember_orders(user_id, list(imported_orders.values()))
        refresh_profile(user_id)
        if job["status"] == "cancelled":
            job["message"] = "Gmail sync cancelled. Imported products and invoices are kept."
        else:
            job["coverage_complete"] = job["errors"] == 0
            job["message"] = f"Checked {job['messages_scanned']} retailer emails; imported {job['orders']} orders and {job['invoices']} invoice PDFs."
            if job["errors"]:
                job["message"] += f" {job['errors']} emails could not be fully read; run sync again to retry them."
            _persist(job, "partial" if job["errors"] else "synced")
    except Exception as error:
        job["errors"] += 1
        job["coverage_complete"] = False
        job["message"] = str(error)[:300] if isinstance(error, GmailSyncError) else "Gmail sync could not finish. Try again."
        _persist(job, "failed")
        try:
            refresh_profile(user_id)
        except Exception:
            pass
    finally:
        job["finished_at"] = now_iso()
        with _LOCK:
            job.pop("thread", None)


def disconnect_gmail(user_id: str) -> dict[str, Any]:
    stored = db.get_gmail_token(user_id)
    with _LOCK:
        job = _JOBS.get(user_id)
        if job and job["status"] in _ACTIVE:
            job["status"] = "cancelled"
    revoke_error = False
    if stored:
        try:
            refresh_token = _decrypt_refresh_token(user_id, stored["refresh_token_ciphertext"])
            request = urllib.request.Request("https://oauth2.googleapis.com/revoke",
                data=urllib.parse.urlencode({"token": refresh_token}).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with urllib.request.urlopen(request, timeout=15):
                pass
        except (urllib.error.URLError, urllib.error.HTTPError, GmailSyncError):
            revoke_error = True
        db.delete_gmail_token(user_id)
    message = "Gmail disconnected. Imported orders and invoices remain in your history."
    if revoke_error:
        message = "Gmail was disconnected here, but Google could not confirm access revocation. Remove Artha in your Google Account permissions to revoke it fully."
    return db.save_account_connection(user_id, "gmail", stored["account_email"] if stored else "", status="disconnected", details={"message": message})
