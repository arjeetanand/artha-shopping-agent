from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.auth import AuthError, app_redirect_url, begin_google_auth, clear_session_cookie, complete_google_auth, current_user, google_configured, logout, session_cookie
    from backend.clients import AnakinClient, BriefModel
    from backend.db import db
    from backend.settings import is_production
    from backend.usage import get_usage_summary, runtime_name
    from backend.voice import VoiceError, VoiceService
    from backend.workflow import create_purchase_plan, run_search
    from backend.orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return
else:
    from .auth import AuthError, app_redirect_url, begin_google_auth, clear_session_cookie, complete_google_auth, current_user, google_configured, logout, session_cookie
    from .clients import AnakinClient, BriefModel
    from .db import db
    from .settings import is_production
    from .usage import get_usage_summary, runtime_name
    from .voice import VoiceError, VoiceService
    from .workflow import create_purchase_plan, run_search
    from .orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return


HOST = os.environ.get("SHOPPINGHELP_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHOPPINGHELP_PORT", "8000"))


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "artha-api/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[artha] {self.address_string()} - {format % args}")

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = {item.strip() for item in os.environ.get("SHOPPINGHELP_CORS_ORIGIN", "").split(",") if item.strip()}
        if origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self._cors()
        self.end_headers()

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8_000_000:
                raise ApiError("Request is too large", 413)
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ApiError("JSON body must be an object")
            return value
        except json.JSONDecodeError as error:
            raise ApiError(f"Invalid JSON: {error.msg}") from error

    def _user(self) -> dict[str, Any] | None:
        return current_user(self.headers.get("Cookie"))

    def _require_user(self) -> dict[str, Any]:
        user = self._user()
        if not user:
            raise ApiError("Sign in with Google to save a private purchase plan.", 401)
        return user

    def _app_origin(self) -> str | None:
        referer = self.headers.get("Referer", "")
        parsed = urlparse(referer)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                brief = BriefModel().status()
                voice = VoiceService().status()
                self._send(
                    200,
                    {
                        "ok": True,
                        "google_configured": google_configured(),
                        "anakin_configured": AnakinClient().configured,
                        "ai": brief,
                        "voice": voice,
                        "environment": os.environ.get("APP_ENV", "development"),
                    },
                )
                return
            if path == "/api/auth/session":
                user = self._user()
                self._send(200, {"authenticated": bool(user), "user": user})
                return
            if path == "/api/auth/google/start":
                self._redirect(begin_google_auth((query.get("next") or ["/"])[0], self._app_origin()))
                return
            if path == "/api/auth/google/callback":
                if query.get("error"):
                    self._redirect(f"{app_redirect_url('/')}?{urlencode({'auth_error': 'google_cancelled'})}")
                    return
                user, token, next_path = complete_google_auth((query.get("code") or [""])[0], (query.get("state") or [""])[0])
                destination = next_path if next_path.startswith(("http://", "https://")) else app_redirect_url(next_path)
                separator = "&" if "?" in destination else "?"
                self._redirect(f"{destination}{separator}{urlencode({'auth': 'success'})}", session_cookie(token))
                return
            if path == "/api/usage":
                if is_production():
                    self._require_user()
                try:
                    days = int((query.get("days") or ["30"])[0])
                except ValueError as error:
                    raise ApiError("Usage window must be a number of days", 400) from error
                if not 1 <= days <= 365:
                    raise ApiError("Usage window must be between 1 and 365 days", 400)
                requested_runtime = (query.get("runtime") or ["all"])[0].lower()
                if requested_runtime not in {"all", "local", "production"}:
                    raise ApiError("Usage runtime must be all, local, or production", 400)
                brief = BriefModel().status()
                voice = VoiceService().status()
                summary = get_usage_summary(
                    days=days,
                    runtime=None if requested_runtime == "all" else requested_runtime,
                )
                self._send(
                    200,
                    {
                        **summary,
                        "active_runtime": runtime_name(),
                        "environment": os.environ.get("APP_ENV", "development"),
                        "active_ai": brief,
                        "active_voice": voice,
                        "anakin_configured": AnakinClient().configured,
                        "google_configured": google_configured(),
                    },
                )
                return
            if path == "/api/plans":
                user = self._require_user()
                self._send(200, {"plans": db.list_purchase_plans(user["id"])})
                return
            if path == "/api/orders":
                user = self._require_user()
                self._send(200, {"orders": list_orders(user["id"])})
                return
            if path.startswith("/api/orders/"):
                user = self._require_user()
                order_id = path.removeprefix("/api/orders/").strip()
                if not order_id or "/" in order_id:
                    raise ApiError("Order not found", 404)
                self._send(200, {"order": get_order(order_id, user["id"])})
                return
            if path == "/api/voice/status":
                self._send(200, VoiceService().status())
                return
            raise ApiError("Not found", 404)
        except AuthError as error:
            if path == "/api/auth/google/callback":
                self._redirect(f"{app_redirect_url('/')}?{urlencode({'auth_error': 'google_failed'})}")
                return
            self._send(error.status, {"error": str(error)})
        except ApiError as error:
            self._send(error.status, {"error": str(error)})
        except OrderError as error:
            self._send(400, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            payload = self._read_json()
            if path == "/api/agent/search":
                self._send(200, run_search(payload))
                return
            if path == "/api/plans":
                user = self._require_user()
                self._send(201, {"plan": create_purchase_plan(payload, user["id"])})
                return
            if path == "/api/orders":
                user = self._require_user()
                self._send(201, {"order": create_order(payload, user["id"])})
                return
            if path.startswith("/api/orders/") and path.endswith("/cancel"):
                user = self._require_user()
                order_id = path.removeprefix("/api/orders/").removesuffix("/cancel").strip("/")
                if not order_id:
                    raise ApiError("Order not found", 404)
                self._send(200, {"order": cancel_order(order_id, user["id"])})
                return
            if path.startswith("/api/orders/") and path.endswith("/advance"):
                user = self._require_user()
                order_id = path.removeprefix("/api/orders/").removesuffix("/advance").strip("/")
                if not order_id:
                    raise ApiError("Order not found", 404)
                self._send(200, {"order": advance_order(order_id, user["id"])})
                return
            if path.startswith("/api/orders/") and path.endswith("/return"):
                user = self._require_user()
                order_id = path.removeprefix("/api/orders/").removesuffix("/return").strip("/")
                if not order_id:
                    raise ApiError("Order not found", 404)
                self._send(200, {"order": request_return(order_id, user["id"])})
                return
            if path.startswith("/api/orders/") and path.endswith("/refund"):
                user = self._require_user()
                order_id = path.removeprefix("/api/orders/").removesuffix("/refund").strip("/")
                if not order_id:
                    raise ApiError("Order not found", 404)
                self._send(200, {"order": complete_refund(order_id, user["id"])})
                return
            if path == "/api/auth/logout":
                logout(self.headers.get("Cookie"))
                self._send(200, {"ok": True}, {"Set-Cookie": clear_session_cookie()})
                return
            if path == "/api/voice/warm":
                self._send(200, VoiceService().warm())
                return
            if path == "/api/voice/speak":
                voice = VoiceService()
                if voice.provider == "browser":
                    self._send(200, {"provider": "browser", "text": str(payload.get("text") or "")[:1800]})
                    return
                audio, content_type = voice.speak(str(payload.get("text") or ""))
                self._send_bytes(200, audio, content_type)
                return
            raise ApiError("Not found", 404)
        except AuthError as error:
            self._send(error.status, {"error": str(error)})
        except VoiceError as error:
            self._send(503, {"error": str(error)})
        except ApiError as error:
            self._send(error.status, {"error": str(error)})
        except OrderError as error:
            self._send(400, {"error": str(error)})
        except ValueError as error:
            self._send(400, {"error": str(error)})
        except RuntimeError as error:
            self._send(503, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as err:
        if err.errno == 48:
            print(f"[artha] ❌ Error: Port {PORT} is already in use by another process.", file=sys.stderr)
            print(f"[artha] Run: lsof -ti :{PORT} | xargs kill -9", file=sys.stderr)
        raise
    print(f"Artha API listening on http://{HOST}:{PORT}")
    print("Google OAuth, Anakin extraction, provider routing, and voice status are ready.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Artha API")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
