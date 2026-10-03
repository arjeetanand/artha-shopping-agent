from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.auth import AuthError, app_redirect_url, begin_google_auth, clear_oauth_state_cookie, clear_session_cookie, complete_google_auth, current_user, google_configured, logout, oauth_state_cookie, session_cookie
    from backend.clients import AnakinClient, BriefModel
    from backend.db import db
    from backend.settings import is_production
    from backend.usage import get_usage_summary, runtime_name
    from backend.voice import VoiceError, VoiceService
    from backend.workflow import create_purchase_plan, run_refinement, run_search
    from backend.orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return
    from backend.payments import PaymentError, create_payment_order, payment_status, verify_payment
    from backend.jobs import allow_search_request, get_search_job, submit_search
    from backend.voice_limits import reserve_global_voice_call
else:
    from .auth import AuthError, app_redirect_url, begin_google_auth, clear_oauth_state_cookie, clear_session_cookie, complete_google_auth, current_user, google_configured, logout, oauth_state_cookie, session_cookie
    from .clients import AnakinClient, BriefModel
    from .db import db
    from .settings import is_production
    from .usage import get_usage_summary, runtime_name
    from .voice import VoiceError, VoiceService
    from .workflow import create_purchase_plan, run_refinement, run_search
    from .orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return
    from .payments import PaymentError, create_payment_order, payment_status, verify_payment
    from .jobs import allow_search_request, get_search_job, submit_search
    from .voice_limits import reserve_global_voice_call


HOST = os.environ.get("SHOPPINGHELP_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHOPPINGHELP_PORT", "8000"))
_MAX_BODY_BYTES = 8_000_000
_MAX_VOICE_BODY_BYTES = 16 * 1024
_BODY_READ_TIMEOUT_SECONDS = 15
_HEADER_READ_TIMEOUT_SECONDS = 10
_SOCKET_IDLE_TIMEOUT_SECONDS = 5
_MAX_ACTIVE_CONNECTIONS = 64
# ponytail: per-process search-handler cap; use shared admission if the API scales to multiple workers.
_SEARCH_REQUEST_CAPACITY = threading.BoundedSemaphore(8)
_VOICE_REQUESTS_PER_MINUTE = 5
_MAX_TRACKED_VOICE_CLIENTS = 4096
_VOICE_CAPACITY = threading.BoundedSemaphore(2)
_voice_admission_lock = threading.Lock()
_voice_requests_by_client: dict[str, deque[float]] = {}
_last_voice_client_cleanup = 0.0


def _admit_paid_voice_request(client_ip: str) -> int | None:
    """Reserve per-IP, global-hourly, and in-flight capacity for paid voice."""
    global _last_voice_client_cleanup
    now = time.monotonic()
    with _voice_admission_lock:
        if now - _last_voice_client_cleanup >= 60:
            for ip, requests in list(_voice_requests_by_client.items()):
                while requests and now - requests[0] >= 60:
                    requests.popleft()
                if not requests:
                    _voice_requests_by_client.pop(ip, None)
            _last_voice_client_cleanup = now

        requests = _voice_requests_by_client.get(client_ip)
        if requests is not None:
            while requests and now - requests[0] >= 60:
                requests.popleft()
            if not requests:
                _voice_requests_by_client.pop(client_ip, None)
                requests = None
        if requests is None and len(_voice_requests_by_client) >= _MAX_TRACKED_VOICE_CLIENTS:
            return 429
        if requests is not None and len(requests) >= _VOICE_REQUESTS_PER_MINUTE:
            return 429
        if not _VOICE_CAPACITY.acquire(blocking=False):
            return 503

        try:
            if not reserve_global_voice_call():
                _VOICE_CAPACITY.release()
                return 429
        except Exception:
            _VOICE_CAPACITY.release()
            raise

        if requests is None:
            requests = deque()
            _voice_requests_by_client[client_ip] = requests
        requests.append(now)
        return None


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Keep accepted handler threads bounded even when clients stall."""

    def __init__(self, server_address: Any, RequestHandlerClass: type[BaseHTTPRequestHandler], bind_and_activate: bool = True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self._connection_slots = threading.BoundedSemaphore(_MAX_ACTIVE_CONNECTIONS)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "artha-api/1.0"

    def setup(self) -> None:
        self.timeout = _SOCKET_IDLE_TIMEOUT_SECONDS
        super().setup()

    def _expire_header_read(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def handle_one_request(self) -> None:
        """Apply a total deadline across the request line and all headers."""
        header_timer = threading.Timer(_HEADER_READ_TIMEOUT_SECONDS, self._expire_header_read)
        header_timer.daemon = True
        header_timer.start()
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                header_timer.cancel()
                self.requestline = ""
                self.request_version = ""
                self.command = ""
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                header_timer.cancel()
                self.close_connection = True
                return
            if not self.parse_request():
                header_timer.cancel()
                return
            header_timer.cancel()
            method_name = "do_" + self.command
            if not hasattr(self, method_name):
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, f"Unsupported method ({self.command!r})")
                return
            getattr(self, method_name)()
            self.wfile.flush()
        except (TimeoutError, OSError):
            self.close_connection = True
            return
        finally:
            header_timer.cancel()

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

    def _redirect(self, location: str, cookie: str | None = None, extra_cookies: tuple[str, ...] = ()) -> None:
        if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in location):
            raise ApiError("Invalid redirect target")
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for value in (cookie, *extra_cookies):
            if value:
                self.send_header("Set-Cookie", value)
        self._cors()
        self.end_headers()

    def _read_json(self, max_bytes: int = _MAX_BODY_BYTES) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise ApiError("Invalid Content-Length")
            if length > max_bytes:
                raise ApiError("Request is too large", 413)
            if length:
                deadline = time.monotonic() + _BODY_READ_TIMEOUT_SECONDS
                previous_timeout = self.connection.gettimeout()
                chunks = []
                remaining = length
                try:
                    while remaining:
                        timeout = deadline - time.monotonic()
                        if timeout <= 0:
                            raise ApiError("Request body timed out", 408)
                        self.connection.settimeout(timeout)
                        chunk = self.rfile.read1(min(64_000, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                except (TimeoutError, socket.timeout) as error:
                    raise ApiError("Request body timed out", 408) from error
                finally:
                    self.connection.settimeout(previous_timeout)
                raw = b"".join(chunks)
            else:
                raw = b"{}"
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
                payment = payment_status()
                self._send(
                    200,
                    {
                        "ok": True,
                        "google_configured": google_configured(),
                        "anakin_configured": AnakinClient().configured,
                        "ai": brief,
                        "voice": voice,
                        "payment": payment,
                        "payment_provider": payment["provider"],
                        "payment_configured": payment["configured"],
                        "environment": os.environ.get("APP_ENV", "development"),
                    },
                )
                return
            if path == "/api/auth/session":
                user = self._user()
                self._send(200, {"authenticated": bool(user), "user": user})
                return
            if path.startswith("/api/agent/search/jobs/"):
                job_id = path.removeprefix("/api/agent/search/jobs/").strip()
                if not job_id or "/" in job_id:
                    raise ApiError("Research job not found", 404)
                job = get_search_job(job_id)
                if not job:
                    raise ApiError("Research job not found", 404)
                self._send(200, job)
                return
            if path == "/api/auth/google/start":
                authorize_url = begin_google_auth((query.get("next") or ["/"])[0], self._app_origin())
                state = (parse_qs(urlparse(authorize_url).query).get("state") or [""])[0]
                if not state:
                    raise AuthError("Google sign-in could not be started.", 500)
                self._redirect(authorize_url, oauth_state_cookie(state))
                return
            if path == "/api/auth/google/callback":
                state = (query.get("state") or [""])[0]
                if query.get("error"):
                    clear_cookie = clear_oauth_state_cookie(state)
                    self._redirect(
                        f"{app_redirect_url('/')}?{urlencode({'auth_error': 'google_cancelled'})}",
                        extra_cookies=(clear_cookie,) if clear_cookie else (),
                    )
                    return
                user, token, next_path = complete_google_auth((query.get("code") or [""])[0], state, self.headers.get("Cookie"))
                destination = next_path if next_path.startswith(("http://", "https://")) else app_redirect_url(next_path)
                separator = "&" if "?" in destination else "?"
                clear_cookie = clear_oauth_state_cookie(state)
                self._redirect(
                    f"{destination}{separator}{urlencode({'auth': 'success'})}",
                    session_cookie(token),
                    (clear_cookie,) if clear_cookie else (),
                )
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
                state = (query.get("state") or [""])[0]
                clear_cookie = clear_oauth_state_cookie(state)
                self._redirect(
                    f"{app_redirect_url('/')}?{urlencode({'auth_error': 'google_failed'})}",
                    extra_cookies=(clear_cookie,) if clear_cookie else (),
                )
                return
            self._send(error.status, {"error": str(error)})
        except ApiError as error:
            self._send(error.status, {"error": str(error)})
        except OrderError as error:
            self._send(400, {"error": str(error)})
        except PaymentError as error:
            self._send(error.status, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        search_request_admitted = False
        voice_request_admitted = False
        try:
            if path in {"/api/agent/search/jobs", "/api/agent/search", "/api/agent/refine"}:
                if not allow_search_request(self.client_address[0]):
                    raise ApiError("Too many research requests; try again shortly.", 429)
                if not _SEARCH_REQUEST_CAPACITY.acquire(blocking=False):
                    raise ApiError("Research service is busy; try again shortly.", 503)
                search_request_admitted = True
            payload = self._read_json(_MAX_VOICE_BODY_BYTES if path == "/api/voice/speak" else _MAX_BODY_BYTES)
            if path == "/api/agent/search/jobs":
                self._send(202, submit_search(payload))
                return
            if path == "/api/agent/search":
                self._send(200, run_search(payload))
                return
            if path == "/api/agent/refine":
                self._send(200, run_refinement(payload))
                return
            if path == "/api/plans":
                user = self._require_user()
                self._send(201, {"plan": create_purchase_plan(payload, user["id"])})
                return
            if path == "/api/orders":
                user = self._require_user()
                self._send(201, {"order": create_order(payload, user["id"])})
                return
            if path == "/api/payments/order":
                user = self._require_user()
                self._send(201, {"payment": create_payment_order(payload, user)})
                return
            if path == "/api/payments/verify":
                user = self._require_user()
                self._send(201, {"order": verify_payment(payload, user)})
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
                if voice.provider == "elevenlabs":
                    voice_text = str(payload.get("text") or "")
                    if not " ".join(voice_text.split())[:1800]:
                        raise ApiError("There is nothing to speak yet.")
                    admission_error = _admit_paid_voice_request(self.client_address[0])
                    if admission_error:
                        message = "Voice service is busy; try again shortly." if admission_error == 503 else "Voice request limit reached; try again later."
                        raise ApiError(message, admission_error)
                    voice_request_admitted = True
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
        except PaymentError as error:
            self._send(error.status, {"error": str(error)})
        except ValueError as error:
            self._send(400, {"error": str(error)})
        except RuntimeError as error:
            self._send(503, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})
        finally:
            if search_request_admitted:
                _SEARCH_REQUEST_CAPACITY.release()
            if voice_request_admitted:
                _VOICE_CAPACITY.release()


def main() -> None:
    try:
        server = BoundedThreadingHTTPServer((HOST, PORT), Handler)
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
