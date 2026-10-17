"""One-batch portal-to-backend Flipkart sync contract using a temporary database."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def call(base: str, path: str, *, cookie: str = "", origin: str = "http://127.0.0.1:5176", body: dict | None = None):
    headers = {"Origin": origin}
    if cookie:
        headers["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base + path, data=data, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def order_record(order_id: str, order_date: str) -> dict:
    timestamp = int((date.fromisoformat(order_date) - date(1970, 1, 1)).total_seconds() * 1000)
    return {
        "orderMetaData": {"orderId": order_id, "orderDate": timestamp},
        "orderMoneyDataBag": {"amount": 1299.0},
        "productDataBag": {
            "LISTING": {
                "productBasicData": {"title": "Blue linen shirt", "url": "/blue-shirt/p/itm12345"},
                "productAttribute": {"storePath": "/blue-shirt/p/itm12345", "brand": "Example", "size": "L", "color": "Blue"},
            }
        },
        "units": {
            "UNIT": {
                "metaData": {"listingId": "LISTING", "quantity": 1, "status": {"key": "Delivered"}},
                "moneyDataBag": {"amount": 1299.0},
            }
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="artha-retailer-ext-", dir="/private/tmp") as directory:
        app_origin = "http://127.0.0.1:5176"
        os.environ.update({
            "SHOPPINGHELP_DB_PATH": str(Path(directory) / "sync.sqlite3"),
            "SHOPPINGHELP_PRIVATE_DIR": str(Path(directory) / "private"),
            "APP_ENV": "development",
            "SHOPPINGHELP_APP_URL": app_origin,
            "SHOPPINGHELP_CORS_ORIGIN": app_origin,
        })
        from backend.auth import session_cookie
        from backend.db import db
        from backend.server import BoundedThreadingHTTPServer, Handler
        from unittest.mock import patch

        server = BoundedThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            user = db.upsert_google_user(google_sub="retailer-extension-test", email="buyer@example.com", name="Buyer", picture="")
            cookie = session_cookie(db.create_session(user["id"])).split(";", 1)[0]
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            generic_pages = {
                "amazon": [{"url": "https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2026", "orders": [{
                    "url": "https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2026", "orderId": "111-1234567-1234567", "orderDate": yesterday,
                    "text": f"Order ID: 111-1234567-1234567\nOrder placed on {yesterday}\nDelivered\nOrder total ₹1,299.00",
                    "products": [{"name": "Blue linen shirt", "url": "https://www.amazon.in/dp/B000TEST01", "text": "Size: L\nColor: Blue", "price": "₹1,299.00"}],
                }]}],
                "myntra": [{"url": "https://www.myntra.com/my/orders", "orders": [{
                    "url": "https://www.myntra.com/my/orders", "orderId": "MN123456789", "orderDate": yesterday,
                    "text": f"Order ID: MN123456789\nOrder placed on {yesterday}\nDelivered",
                    "products": [{"name": "Olive cotton kurta", "url": "https://www.myntra.com/olive-kurta/123/buy", "text": "Size: M\nColor: Olive", "price": "₹1,599.00"}],
                }]}],
                "ajio": [{"url": "https://www.ajio.com/my-account/orders", "orders": [{
                    "url": "https://www.ajio.com/my-account/orders", "orderId": "AJIO123456789", "orderDate": yesterday,
                    "text": f"Order ID: AJIO123456789\nOrder placed on {yesterday}\nShipped",
                    "products": [{"name": "Black casual shirt", "url": "https://www.ajio.com/black-shirt/p/123456789", "text": "Size: S\nColour: Black", "price": "₹999.00"}],
                }]}],
            }
            payloads = {provider: {"provider": provider, "pages": pages, "stop_reason": "history_end"}
                        for provider, pages in generic_pages.items()}
            payloads["flipkart"] = {"provider": "flipkart", "pages": [{
                "SESSION": {"secureToken": "never-persist-this"},
                "RESPONSE": {"multipleOrderDetailsView": {
                    "orders": [order_record("OD12345678901234567890", yesterday)], "moreOrder": False,
                }},
            }], "stop_reason": "history_end"}

            with patch("backend.taste_memory.embed_documents", return_value=([[1.0] + [0.0] * 31], "test:embedding")):
                for provider, payload in payloads.items():
                    endpoint = "/api/profile/retailer-extension/submit"
                    assert call(base, endpoint, body=payload)[0] == 401
                    if provider == "flipkart":
                        assert call(base, endpoint, cookie=cookie, origin="https://evil.example", body=payload)[0] == 403
                    status, response = call(base, endpoint, cookie=cookie, body=payload)
                    assert status == 202, response
                    deadline = time.time() + 10
                    connection = None
                    while time.time() < deadline:
                        _, result = call(base, "/api/profile/connections", cookie=cookie)
                        connection = next(item for item in result["connections"] if item["provider"] == provider)
                        if connection["status"] not in {"indexing", "syncing"}:
                            break
                        time.sleep(0.05)
                    assert connection["status"] == "synced", connection
                    assert connection["details"]["pages"] == 1
                    assert connection["details"]["orders"] == 1
                    assert connection["details"]["coverage_complete"] is True
                    assert connection["details"]["invoice_support"] is False
                    assert "SESSION" not in connection["details"]

            orders = db.list_orders(user["id"])
            assert len(orders) == 4 and {order["payment_provider"] for order in orders} == set(payloads)
            disconnect = {"provider": "ajio"}
            assert call(base, "/api/profile/retailer-extension/disconnect", cookie=cookie, origin="https://evil.example", body=disconnect)[0] == 403
            assert call(base, "/api/profile/retailer-extension/disconnect", cookie=cookie, body=disconnect)[0] == 200
            assert next(item for item in db.list_account_connections(user["id"]) if item["provider"] == "ajio")["status"] == "disconnected"
            assert len(db.list_orders(user["id"])) == 4
            assert db.list_taste_memories(user["id"])
            print("retailer_extension_contract_ok")
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    main()
