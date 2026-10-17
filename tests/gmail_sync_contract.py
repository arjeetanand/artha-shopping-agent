"""Exercise Gmail OAuth, receipt import, invoice access, dedupe, and disconnect."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _request(base: str, path: str, *, method: str = "GET", cookie: str = "", payload: dict | None = None):
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        response = urllib.request.build_opener(_NoRedirect).open(request, timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def _pdf(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): writer._add_object(font)})})
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _gmail_message(sender: str, subject: str, product: str, product_url: str, invoice: bytes, date_ms: str):
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    html = f'<a href="{product_url}">{product}</a>'.encode("utf-8")
    return {
        "internalDate": date_ms,
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "parts": [
                {"mimeType": "text/html", "body": {"data": encode(html)}},
                {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"data": encode(invoice)}},
            ],
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="artha-gmail-e2e-", dir="/private/tmp") as directory:
        os.environ.update({
            "SHOPPINGHELP_DB_PATH": str(Path(directory) / "gmail.sqlite3"),
            "SHOPPINGHELP_PRIVATE_DIR": str(Path(directory) / "private"),
            "APP_ENV": "development",
            "SHOPPINGHELP_SEARCH_MODE": "fixture",
            "GOOGLE_CLIENT_ID": "gmail-test-client",
            "GOOGLE_CLIENT_SECRET": "gmail-test-client-secret",
            "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/api/auth/google/callback",
            "SHOPPINGHELP_APP_URL": "http://127.0.0.1:5173",
        })
        from backend import gmail_sync, taste_memory
        from backend.auth import GMAIL_READONLY_SCOPE, session_cookie
        from backend.db import db
        from backend.server import BoundedThreadingHTTPServer, Handler

        server = BoundedThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            user = db.upsert_google_user(google_sub="gmail-e2e", email="buyer@example.com", name="Buyer", picture="")
            session = db.create_session(user["id"])
            cookie = session_cookie(session).split(";", 1)[0]
            vector = [1.0] + [0.0] * 31
            date_ms = str(int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000))
            messages = {
                "amazon-e2e": _gmail_message("receipts@amazon.in", "Order 111-1234567-1234567 confirmed",
                    "Blue linen shirt", "https://www.amazon.in/dp/B000TEST", _pdf("Product: Blue linen shirt"), date_ms),
                "flipkart-e2e": _gmail_message("orders@flipkart.com", "Order OD123456789012345 confirmed",
                    "Black running shoes", "https://www.flipkart.com/item/p/itm123", _pdf("Product: Black running shoes"), date_ms),
                "myntra-e2e": _gmail_message("orders@myntra.com", "Order MN123456789 placed",
                    "Olive cotton kurta", "https://www.myntra.com/kurta/item-123/buy", _pdf("Product: Olive cotton kurta"), date_ms),
            }
            list_calls: list[dict[str, str]] = []
            message_calls: list[str] = []

            def google_get(path: str, access_token: str, params: dict[str, str] | None = None):
                assert access_token == "gmail-access-token"
                if path == "messages":
                    list_calls.append(params or {})
                    page_messages = list(messages)[:2] if not (params or {}).get("pageToken") else list(messages)[2:]
                    next_page = {"nextPageToken": "next-page"} if not (params or {}).get("pageToken") else {}
                    return {"messages": [{"id": message_id} for message_id in page_messages], **next_page}
                message_id = path.removeprefix("messages/")
                assert message_id in messages, path
                message_calls.append(message_id)
                return messages[message_id]

            start_status, start_headers, _ = _request(base, "/api/auth/gmail/start?next=%2Ftaste-graph", cookie=cookie)
            assert start_status == 302
            authorize_url = start_headers["Location"]
            auth_query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorize_url).query)
            assert auth_query["scope"] == [f"openid email {GMAIL_READONLY_SCOPE}"]
            assert auth_query["redirect_uri"] == ["http://127.0.0.1:8000/api/auth/google/callback"], auth_query["redirect_uri"]
            assert auth_query["access_type"] == ["offline"]
            assert auth_query["code_challenge_method"] == ["S256"]
            state = auth_query["state"][0]
            state_cookie = next(value.split(";", 1)[0] for value in start_headers.get_all("Set-Cookie") if state in value)
            callback_cookie = f"{cookie}; {state_cookie}"
            exchange_payloads: list[dict[str, str]] = []

            def exchange(_url: str, payload: dict[str, str]):
                exchange_payloads.append(payload)
                return {"access_token": "gmail-access-token", "refresh_token": "sensitive-refresh-token"}

            with (patch("backend.auth._post_form_json", side_effect=exchange),
                  patch("backend.auth._get_userinfo", return_value={"email": "buyer@example.com", "email_verified": True}),
                  patch("backend.gmail_sync._post_form_json", return_value={"access_token": "gmail-access-token"}),
                  patch("backend.gmail_sync._google_get", side_effect=google_get),
                  patch("backend.taste_memory.embed_documents", return_value=([vector], "test:embedding"))):
                callback_path = "/api/auth/google/callback?" + urllib.parse.urlencode({"code": "test-code", "state": state})
                callback_status, callback_headers, _ = _request(base, callback_path, cookie=callback_cookie)
                assert callback_status == 302
                assert callback_headers["Location"].startswith("http://127.0.0.1:5173/taste-graph?gmail=connected")
                assert exchange_payloads[0]["redirect_uri"] == "http://127.0.0.1:8000/api/auth/google/callback"
                assert db.get_gmail_token(user["id"])["refresh_token_ciphertext"] != "sensitive-refresh-token"
                first_sync_thread = gmail_sync._JOBS[user["id"]]["thread"]
                first_sync_thread.join(10)
                assert not first_sync_thread.is_alive()

                status, status_headers, status_body = _request(base, "/api/profile/gmail/status", cookie=cookie)
                assert status == 200
                connection = json.loads(status_body)["connection"]
                assert connection["status"] == "synced", connection
                assert connection["details"]["messages_scanned"] == 3
                assert connection["details"]["orders"] == 3
                assert connection["details"]["invoices"] == 3
                assert connection["details"]["coverage_complete"] is True
                assert list_calls[0]["q"] == gmail_sync.GMAIL_SEARCH
                assert list_calls[0]["maxResults"] == "500"
                assert list_calls[1]["pageToken"] == "next-page"
                assert set(message_calls) == set(messages)

                order_status, _, order_body = _request(base, "/api/profile/orders", cookie=cookie)
                orders = json.loads(order_body)["orders"]
                assert order_status == 200 and len(orders) == 3
                assert {order["payment_provider"] for order in orders} == {"amazon", "flipkart", "myntra"}
                assert all(order["data_source"] == "gmail_receipt" and order["total_verified"] is False for order in orders)
                assert {order["items"][0]["name"] for order in orders} == {"Blue linen shirt", "Black running shoes", "Olive cotton kurta"}

                invoice_status, _, invoice_body = _request(base, "/api/profile/invoices", cookie=cookie)
                invoices = json.loads(invoice_body)["invoices"]
                assert invoice_status == 200 and len(invoices) == 3
                for invoice in invoices:
                    record = db.get_retailer_invoice(user["id"], invoice["id"])
                    assert "Product:" in record["extracted_text"]
                    file_status, file_headers, file_data = _request(base, f"/api/profile/invoices/{invoice['id']}", cookie=cookie)
                    assert file_status == 200 and file_headers["Content-Type"] == "application/pdf"
                    assert file_data.startswith(b"%PDF-")

                connection_status, _, connection_body = _request(base, "/api/profile/connections", cookie=cookie)
                assert connection_status == 200
                assert "sensitive-refresh-token" not in connection_body.decode("utf-8")
                memories_status, _, memories_body = _request(base, "/api/profile/memories", cookie=cookie)
                memories = json.loads(memories_body)["memories"]
                assert memories_status == 200
                assert {"Blue linen shirt", "Black running shoes", "Olive cotton kurta"}.issubset(
                    {memory["attributes"].get("name") for memory in memories})
                graph_status, _, graph_body = _request(base, "/api/profile/graph", cookie=cookie)
                graph = json.loads(graph_body)
                assert graph_status == 200 and graph["metrics"]["tracked_orders"] == 3

                recommendation_status, _, recommendation_body = _request(base, "/api/agent/search", method="POST", cookie=cookie,
                    payload={"text": "linen shirt under ₹2,000 in Pune within 7 days", "use_profile": True})
                recommendation = json.loads(recommendation_body)
                assert recommendation_status == 200, recommendation
                assert any(memory["attributes"].get("name") == "Blue linen shirt"
                    for memory in recommendation["intent"]["taste_context"]["memories"])

                other = db.upsert_google_user(google_sub="gmail-e2e-other", email="other@example.com", name="Other", picture="")
                other_cookie = session_cookie(db.create_session(other["id"])).split(";", 1)[0]
                assert len(json.loads(_request(base, "/api/profile/orders", cookie=other_cookie)[2])["orders"]) == 0
                foreign_status, _, _ = _request(base, f"/api/profile/invoices/{invoices[0]['id']}", cookie=other_cookie)
                assert foreign_status == 404

                sync_status, _, sync_body = _request(base, "/api/profile/gmail/sync", method="POST", cookie=cookie, payload={})
                assert sync_status == 202, sync_body
                second_sync_thread = gmail_sync._JOBS[user["id"]]["thread"]
                second_sync_thread.join(10)
                assert not second_sync_thread.is_alive()
                assert len(db.list_orders(user["id"])) == 3
                assert len(db.list_retailer_invoices(user["id"])) == 3
                assert len(message_calls) == 3
                assert gmail_sync._JOBS[user["id"]]["skipped"] == 3

                real_urlopen = urllib.request.urlopen
                revoke_requests: list[bytes] = []

                class _Revoked:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                def urlopen(request, *args, **kwargs):
                    if isinstance(request, urllib.request.Request) and request.full_url == "https://oauth2.googleapis.com/revoke":
                        revoke_requests.append(request.data or b"")
                        return _Revoked()
                    return real_urlopen(request, *args, **kwargs)

                with patch.object(urllib.request, "urlopen", side_effect=urlopen):
                    disconnect_status, _, disconnect_body = _request(base, "/api/profile/gmail/disconnect", method="POST", cookie=cookie, payload={})
                assert disconnect_status == 200, disconnect_body
                assert b"sensitive-refresh-token" in urllib.parse.parse_qs(revoke_requests[0].decode("utf-8"))["token"][0].encode()
                assert db.get_gmail_token(user["id"]) is None
                assert gmail_sync.gmail_status(user["id"])["status"] == "disconnected"
                assert len(db.list_orders(user["id"])) == 3
                assert len(db.list_retailer_invoices(user["id"])) == 3
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
    print("gmail_sync_contract_ok")


if __name__ == "__main__":
    main()
