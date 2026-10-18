from __future__ import annotations

import json
import os
import signal
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
    from backend.auth import AuthError, app_redirect_url, begin_google_auth, begin_gmail_auth, clear_oauth_state_cookie, clear_session_cookie, complete_google_auth, complete_gmail_auth, current_user, google_configured, logout, oauth_state_cookie, session_cookie
    from backend.clients import AnakinClient, BriefModel, search_status
    from backend.db import db, now_iso
    from backend.settings import is_production, setting
    from backend.usage import get_usage_summary, runtime_name
    from backend.voice import VoiceError, VoiceService
    from backend.workflow import create_purchase_plan, run_refinement, run_search
    from backend.orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return
    from backend.payments import PaymentError, create_payment_order, payment_status, verify_payment
    from backend.jobs import allow_search_request, get_search_job, submit_search
    from backend.voice_limits import reserve_global_voice_call
    from backend.profile import build_context_graph, get_or_create_profile, refresh_profile
    from backend.connections import start_sync, list_connections, cancel_sync, disconnect, invoice_file
    from backend.taste_memory import public_memories, remember_link, save_memories, reindex_memories
    from backend.gmail_sync import GmailSyncError, cancel_gmail_sync, disconnect_gmail, gmail_status, save_gmail_connection, start_gmail_sync
    from backend.retailer_extension_sync import cancel as cancel_retailer_extension, disconnect as disconnect_retailer_extension, submit_batch as submit_retailer_extension_batch
    from backend.conversation import confirm_instagram_post_and_search, get_or_start_session, process_conversation_turn
    from backend.social import resolve_instagram_reference, save_uploaded_instagram_reference, screenshot_file_for_reference
else:
    from .auth import AuthError, app_redirect_url, begin_google_auth, begin_gmail_auth, clear_oauth_state_cookie, clear_session_cookie, complete_google_auth, complete_gmail_auth, current_user, google_configured, logout, oauth_state_cookie, session_cookie
    from .clients import AnakinClient, BriefModel, search_status
    from .db import db, now_iso
    from .settings import is_production, setting
    from .usage import get_usage_summary, runtime_name
    from .voice import VoiceError, VoiceService
    from .workflow import create_purchase_plan, run_refinement, run_search
    from .orders import OrderError, advance_order, cancel_order, complete_refund, create_order, get_order, list_orders, request_return
    from .payments import PaymentError, create_payment_order, payment_status, verify_payment
    from .jobs import allow_search_request, get_search_job, submit_search
    from .voice_limits import reserve_global_voice_call
    from .profile import build_context_graph, get_or_create_profile, refresh_profile
    from .connections import start_sync, list_connections, cancel_sync, disconnect, invoice_file
    from .taste_memory import public_memories, remember_link, save_memories, reindex_memories
    from .gmail_sync import GmailSyncError, cancel_gmail_sync, disconnect_gmail, gmail_status, save_gmail_connection, start_gmail_sync
    from .retailer_extension_sync import cancel as cancel_retailer_extension, disconnect as disconnect_retailer_extension, submit_batch as submit_retailer_extension_batch
    from .conversation import confirm_instagram_post_and_search, get_or_start_session, process_conversation_turn
    from .social import resolve_instagram_reference, save_uploaded_instagram_reference, screenshot_file_for_reference


HOST = os.environ.get("SHOPPINGHELP_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHOPPINGHELP_PORT", "8000"))
_MAX_BODY_BYTES = 8_000_000
_MAX_VOICE_BODY_BYTES = 16 * 1024
_MAX_SOCIAL_BODY_BYTES = 16 * 1024
_BODY_READ_TIMEOUT_SECONDS = 15
_HEADER_READ_TIMEOUT_SECONDS = 10
_SOCKET_IDLE_TIMEOUT_SECONDS = 5
_MAX_ACTIVE_CONNECTIONS = 64
# ponytail: per-process search-handler cap; use shared admission if the API scales to multiple workers.
_SEARCH_REQUEST_CAPACITY = threading.BoundedSemaphore(8)
_SOCIAL_REQUESTS_PER_MINUTE = 5
_MAX_TRACKED_SOCIAL_CLIENTS = 4096
_SOCIAL_CAPACITY = threading.BoundedSemaphore(2)
_social_admission_lock = threading.Lock()
_social_requests_by_client: dict[str, deque[float]] = {}
_last_social_client_cleanup = 0.0
_VOICE_REQUESTS_PER_MINUTE = 10
_MAX_TRACKED_VOICE_CLIENTS = 4096
_VOICE_CAPACITY = threading.BoundedSemaphore(2)
_voice_admission_lock = threading.Lock()
_voice_requests_by_client: dict[str, deque[float]] = {}
_last_voice_client_cleanup = 0.0


def _admit_social_request(client_ip: str) -> int | None:
    """Limit expensive public-page captures by client and in-flight work."""
    global _last_social_client_cleanup
    now = time.monotonic()
    with _social_admission_lock:
        if now - _last_social_client_cleanup >= 60:
            for ip, requests in list(_social_requests_by_client.items()):
                while requests and now - requests[0] >= 60:
                    requests.popleft()
                if not requests:
                    _social_requests_by_client.pop(ip, None)
            _last_social_client_cleanup = now

        requests = _social_requests_by_client.get(client_ip)
        if requests is not None:
            while requests and now - requests[0] >= 60:
                requests.popleft()
            if not requests:
                _social_requests_by_client.pop(client_ip, None)
                requests = None
        if requests is None and len(_social_requests_by_client) >= _MAX_TRACKED_SOCIAL_CLIENTS:
            return 429
        if requests is not None and len(requests) >= _SOCIAL_REQUESTS_PER_MINUTE:
            return 429

        if requests is None:
            requests = deque()
            _social_requests_by_client[client_ip] = requests
        requests.append(now)
        return None if _SOCIAL_CAPACITY.acquire(blocking=False) else 503


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

    def _send_bytes(self, status: int, data: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
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

    def _profile_user_id(self) -> str:
        user = self._user()
        if user:
            return user["id"]
        raise ApiError("Sign in with Google to use a private taste profile.", 401)

    def _assistant_user(self) -> tuple[str, str]:
        user = self._user()
        if user:
            return str(user["id"]), str(user.get("name") or "Arjeet")
        if not is_production():
            local_user = db.get_default_local_user()
            if local_user:
                return str(local_user["id"]), str(local_user.get("name") or "Arjeet")
        return "shopper-local", "Arjeet"

    def _local_connector_request(self) -> None:
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            raise ApiError("Account connection must be started from the local app.", 403)
        origin = self.headers.get("Origin")
        allowed = {setting("SHOPPINGHELP_APP_URL"), *setting("SHOPPINGHELP_CORS_ORIGIN").split(",")}
        if origin and origin.rstrip("/") not in {value.rstrip("/") for value in allowed if value}:
            raise ApiError("Account connection must be started from the app window.", 403)

    def _portal_extension_request(self) -> None:
        origin = self.headers.get("Origin", "").rstrip("/")
        allowed = {setting("SHOPPINGHELP_APP_URL"), *setting("SHOPPINGHELP_CORS_ORIGIN").split(",")}
        if not origin or origin not in {value.strip().rstrip("/") for value in allowed if value.strip()}:
            raise ApiError("Retailer sync must be submitted from the signed-in portal.", 403)

    def _app_origin(self) -> str | None:
        referer = self.headers.get("Referer", "")
        parsed = urlparse(referer)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    def _gmail_callback(self, query: dict[str, list[str]], callback_path: str) -> None:
        state = (query.get("state") or [""])[0]
        clear_cookie = clear_oauth_state_cookie(state, callback_path)
        if query.get("error"):
            db.consume_oauth_state(state)
            self._redirect(f"{app_redirect_url('/taste-graph')}?gmail=cancelled", extra_cookies=(clear_cookie,) if clear_cookie else ())
            return
        user = self._user()
        if not user:
            db.consume_oauth_state(state)
            self._redirect(f"{app_redirect_url('/taste-graph')}?gmail=sign_in_required", extra_cookies=(clear_cookie,) if clear_cookie else ())
            return
        email, refresh_token, next_path = complete_gmail_auth((query.get("code") or [""])[0], state,
            self.headers.get("Cookie"), user["id"])
        save_gmail_connection(user["id"], email, refresh_token)
        try:
            start_gmail_sync(user["id"])
        except Exception:
            pass
        destination = next_path if next_path.startswith(("http://", "https://")) else app_redirect_url(next_path)
        separator = "&" if "?" in destination else "?"
        self._redirect(f"{destination}{separator}gmail=connected", extra_cookies=(clear_cookie,) if clear_cookie else ())

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        gmail_callback_path = ""
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
                        **search_status(),
                        "search_mode": "fixture" if setting("SHOPPINGHELP_SEARCH_MODE", "live").lower() in {"fixture", "sandbox", "mock"} else "live",
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
                user = self._user()
                job = get_search_job(job_id, user["id"] if user else "shopper-local")
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
            if path == "/api/auth/gmail/start":
                user = self._require_user()
                authorize_url = begin_gmail_auth(user["id"], (query.get("next") or ["/taste-graph"])[0], self._app_origin())
                state = (parse_qs(urlparse(authorize_url).query).get("state") or [""])[0]
                redirect_uri = (parse_qs(urlparse(authorize_url).query).get("redirect_uri") or [""])[0]
                callback_path = urlparse(redirect_uri).path
                if not state or not callback_path:
                    raise AuthError("Gmail connection could not be started.", 500)
                self._redirect(authorize_url, oauth_state_cookie(state, callback_path))
                return
            if path == "/api/auth/google/callback":
                state = (query.get("state") or [""])[0]
                if db.oauth_state_purpose(state) == "gmail":
                    gmail_callback_path = path
                    self._gmail_callback(query, gmail_callback_path)
                    return
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
            if path == "/api/auth/gmail/callback":
                gmail_callback_path = path
                self._gmail_callback(query, gmail_callback_path)
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
                        **search_status(),
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
            if path == "/api/profile/taste":
                user_id = self._profile_user_id()
                self._send(200, {**get_or_create_profile(user_id), "connected_accounts": list_connections(user_id)})
                return
            if path == "/api/profile/connections":
                self._send(200, {"connections": list_connections(self._profile_user_id())})
                return
            if path == "/api/profile/gmail/status":
                self._send(200, {"connection": gmail_status(self._profile_user_id())})
                return
            if path == "/api/profile/memories":
                self._send(200, {"memories": public_memories(self._profile_user_id())})
                return
            if path == "/api/profile/invoices":
                self._send(200, {"invoices": db.list_retailer_invoices(self._profile_user_id())})
                return
            if path.startswith("/api/profile/invoices/"):
                file = invoice_file(self._profile_user_id(), path.removeprefix("/api/profile/invoices/"))
                if not file:
                    raise ApiError("Invoice not found", 404)
                self._send_bytes(200,file.read_bytes(),"application/pdf",{"Content-Disposition":"attachment; filename=invoice.pdf","X-Content-Type-Options":"nosniff"})
                return
            if path == "/api/profile/graph":
                user_id = self._profile_user_id()
                search_id = (query.get("search_id") or [""])[0]
                brief = None
                if search_id:
                    saved = db.get_search(search_id)
                    if saved and saved.get("intent", {}).get("_profile_user_id") == user_id:
                        brief = saved.get("intent")
                self._send(200, build_context_graph(user_id, active_brief=brief))
                return
            if path == "/api/profile/orders":
                self._send(200, {"orders": [order for order in db.list_orders(self._profile_user_id()) if order.get("data_source") in {"retailer_session", "gmail_receipt"}]})
                return
            if path == "/api/voice/status":
                self._send(200, VoiceService().status())
                return
            if path == "/api/assistant/session":
                user_id, _ = self._assistant_user()
                session_id = (query.get("session_id") or [""])[0].strip() or None
                reset = (query.get("reset") or [""])[0].strip().lower() in {"1", "true", "yes"}
                if reset:
                    session_id = None
                self._send(200, get_or_start_session(user_id, session_id=session_id, reset=reset))
                return
            if path.startswith("/api/social/screenshots/"):
                ref_id = path.removeprefix("/api/social/screenshots/").strip("/")
                if not ref_id or "/" in ref_id:
                    raise ApiError("Screenshot not found", 404)
                user_id, _ = self._assistant_user()
                file_path = screenshot_file_for_reference(ref_id, user_id)
                if not file_path:
                    raise ApiError("Screenshot not found", 404)
                ext = file_path.suffix.lower()
                mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
                self._send_bytes(200, file_path.read_bytes(), mime, {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
                return
            raise ApiError("Not found", 404)
        except AuthError as error:
            if gmail_callback_path:
                state = (query.get("state") or [""])[0]
                clear_cookie = clear_oauth_state_cookie(state, gmail_callback_path)
                self._redirect(f"{app_redirect_url('/taste-graph')}?gmail=failed", extra_cookies=(clear_cookie,) if clear_cookie else ())
                return
            if path == "/api/auth/google/callback":
                state = (query.get("state") or [""])[0]
                clear_cookie = clear_oauth_state_cookie(state)
                self._redirect(
                    f"{app_redirect_url('/')}?{urlencode({'auth_error': 'google_failed'})}",
                    extra_cookies=(clear_cookie,) if clear_cookie else (),
                )
                return
            if path == "/api/auth/gmail/callback":
                state = (query.get("state") or [""])[0]
                clear_cookie = clear_oauth_state_cookie(state, "/api/auth/gmail/callback")
                self._redirect(f"{app_redirect_url('/taste-graph')}?gmail=failed", extra_cookies=(clear_cookie,) if clear_cookie else ())
                return
            self._send(error.status, {"error": str(error)})
        except ApiError as error:
            self._send(error.status, {"error": str(error)})
        except OrderError as error:
            self._send(400, {"error": str(error)})
        except PaymentError as error:
            self._send(error.status, {"error": str(error)})
        except GmailSyncError as error:
            self._send(409, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        search_request_admitted = False
        social_request_admitted = False
        voice_request_admitted = False
        try:
            if path in {"/api/agent/search/jobs", "/api/agent/search", "/api/agent/refine"}:
                if not allow_search_request(self.client_address[0]):
                    raise ApiError("Too many research requests; try again shortly.", 429)
                if not _SEARCH_REQUEST_CAPACITY.acquire(blocking=False):
                    raise ApiError("Research service is busy; try again shortly.", 503)
                search_request_admitted = True
            elif path == "/api/social/theme":
                admission_error = _admit_social_request(self.client_address[0])
                if admission_error:
                    message = "Style analysis is busy; try again shortly." if admission_error == 503 else "Too many style analyses; try again later."
                    raise ApiError(message, admission_error)
                social_request_admitted = True
            body_limit = 3_000_000 if path == "/api/voice/transcribe" else _MAX_VOICE_BODY_BYTES if path == "/api/voice/speak" else _MAX_SOCIAL_BODY_BYTES if path == "/api/social/theme" else 7_750_000 if path in {"/api/profile/flipkart-extension/submit", "/api/profile/retailer-extension/submit", "/api/social/instagram/upload"} else _MAX_BODY_BYTES
            payload = self._read_json(body_limit)
            if path in {"/api/agent/search/jobs", "/api/agent/search", "/api/agent/refine"}:
                user = self._user()
                payload["user_id"] = user["id"] if user else "shopper-local"
                if not user:
                    payload["use_profile"] = False
            if path == "/api/agent/search/jobs":
                self._send(202, submit_search(payload))
                return
            if path == "/api/agent/search":
                self._send(200, run_search(payload))
                return
            if path == "/api/agent/refine":
                self._send(200, run_refinement(payload))
                return
            if path == "/api/assistant/converse":
                user_id, _ = self._assistant_user()
                message = str(payload.get("message") or payload.get("text") or "").strip()
                if not message:
                    raise ApiError("Message is required", 400)
                session_id = str(payload.get("session_id") or "").strip() or None
                self._send(
                    200,
                    process_conversation_turn(
                        user_id=user_id,
                        text=message,
                        session_id=session_id,
                        reference_image=payload.get("reference_image") if isinstance(payload.get("reference_image"), dict) else None,
                        reference_url=str(payload.get("reference_url") or ""),
                    ),
                )
                return
            if path == "/api/assistant/confirm-reference":
                user_id, _ = self._assistant_user()
                session_id = str(payload.get("session_id") or "").strip()
                reference_id = str(payload.get("reference_id") or "").strip()
                clothing_note = str(payload.get("item_hint") or payload.get("clothing_note") or "").strip()
                if not session_id or not reference_id:
                    raise ApiError("session_id and reference_id are required", 400)
                self._send(
                    200,
                    confirm_instagram_post_and_search(
                        user_id=user_id,
                        session_id=session_id,
                        reference_id=reference_id,
                        item_hint=clothing_note or "T-shirt",
                    ),
                )
                return
            if path == "/api/social/instagram/resolve":
                user_id, _ = self._assistant_user()
                ref_input = str(payload.get("reference") or payload.get("handle") or payload.get("url") or "").strip()
                if not ref_input:
                    raise ApiError("Instagram handle, URL, or friend name is required", 400)
                if len(ref_input) > 2048:
                    raise ApiError("Instagram reference is too long", 400)
                try:
                    max_posts = min(max(int(payload.get("limit") or 5), 1), 5)
                except (TypeError, ValueError) as error:
                    raise ApiError("limit must be a number from 1 to 5", 400) from error
                session = get_or_start_session(
                    user_id,
                    session_id=str(payload.get("session_id") or "").strip() or None,
                )
                resolution = resolve_instagram_reference(
                    user_id,
                    ref_input,
                    friend_name=str(payload.get("friend_name") or session.get("state", {}).get("friend_name") or "")[:60],
                    max_posts=max_posts,
                )
                state = dict(session.get("state") or {})
                state["friend_name"] = resolution.get("friend_name") or state.get("friend_name")
                state["instagram_handle"] = resolution.get("handle") or state.get("instagram_handle")
                posts = resolution.get("posts") if isinstance(resolution.get("posts"), list) else []
                if resolution.get("success") and posts:
                    state["instagram_posts"] = posts
                    state["awaiting_instagram_handle"] = False
                    state["awaiting_post_confirmation"] = True
                else:
                    state["awaiting_instagram_handle"] = True
                    state["awaiting_post_confirmation"] = False
                messages = list(session.get("messages") or [])
                if resolution.get("message"):
                    messages.append({
                        "id": f"instagram-resolution-{session['id']}-{len(messages)}",
                        "role": "assistant",
                        "text": str(resolution["message"]),
                        "created_at": now_iso(),
                    })
                saved = db.save_conversation_session(session["id"], user_id, state, messages)
                self._send(200, {
                    **resolution,
                    "session_id": session["id"],
                    "state": saved["state"],
                    "messages": saved["messages"],
                    "history": session.get("history") or {},
                })
                return
            if path == "/api/social/instagram/upload":
                user_id, _ = self._assistant_user()
                saved_ref = save_uploaded_instagram_reference(
                    user_id=user_id,
                    image_base64=str(payload.get("image_base64") or payload.get("image_data") or ""),
                    mime_type=str(payload.get("mime_type") or "image/jpeg"),
                    source_url=str(payload.get("source_url") or payload.get("post_url") or ""),
                    friend_name=str(payload.get("friend_name") or "Paras"),
                    caption=str(payload.get("caption") or ""),
                    handle=str(payload.get("handle") or ""),
                )
                session_id = str(payload.get("session_id") or "").strip()
                session_data = None
                if session_id:
                    session = db.get_conversation_session(session_id, user_id)
                    if session:
                        state = session.get("state") or {}
                        posts = list(state.get("instagram_posts") or [])
                        posts = [p for p in posts if p.get("id") != saved_ref.get("id")]
                        posts.insert(0, saved_ref)
                        state["instagram_posts"] = posts[:5]
                        state["awaiting_instagram_handle"] = False
                        state["awaiting_post_confirmation"] = True
                        messages = list(session.get("messages") or [])
                        messages.append({
                            "id": f"instagram-upload-{saved_ref['id']}",
                            "role": "assistant",
                            "text": "I saved your uploaded Instagram reference locally. Select it below and confirm the clothing item so I can analyze it and search retailers.",
                            "created_at": saved_ref.get("captured_at"),
                        })
                        session_data = db.save_conversation_session(session_id, user_id, state, messages)
                self._send(201, {"reference": saved_ref, "session": session_data})
                return
            if path == "/api/social/theme":
                try:
                    from .social import extract_theme_from_url
                except ImportError:
                    from backend.social import extract_theme_from_url
                url = str(payload.get("url") or "").strip()
                if not url:
                    raise ApiError("URL is required")
                user = self._user()
                result = extract_theme_from_url(url, user_id=user["id"]) if user else extract_theme_from_url(url)
                if result.get("success") and user:
                    result["memory"] = remember_link(user["id"], result)
                    refresh_profile(user["id"])
                self._send(200, result)
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
            if path == "/api/profile/taste":
                user_id = self._profile_user_id()
                preferences = payload.get("preferences") or payload
                stats = payload.get("stats")
                if not isinstance(preferences, dict) or (stats is not None and not isinstance(stats, dict)):
                    raise ApiError("Preferences and stats must be objects", 400)
                if stats is None:
                    stats = get_or_create_profile(user_id)["stats"]
                self._send(200, db.save_user_profile(user_id, preferences, stats))
                return
            if path == "/api/profile/sync-account":
                user_id = self._profile_user_id()
                self._local_connector_request()
                provider = str(payload.get("provider") or "").strip()
                if payload.get("orders") is not None:
                    raise ApiError("Use Connect to read orders directly from your retailer account.", 400)
                self._send(202, start_sync(user_id,provider))
                return
            if path in {"/api/profile/retailer-extension/submit", "/api/profile/flipkart-extension/submit"}:
                self._portal_extension_request()
                user_id = self._require_user()["id"]
                is_legacy = path.endswith("flipkart-extension/submit")
                if set(payload) != ({"pages", "stop_reason"} if is_legacy else {"provider", "pages", "stop_reason"}):
                    raise ApiError("Retailer sync payload is invalid", 400)
                provider = "flipkart" if is_legacy else payload["provider"]
                connection = submit_retailer_extension_batch(user_id, provider, payload["pages"], payload["stop_reason"])
                self._send(202, {"connection": connection})
                return
            if path in {"/api/profile/retailer-extension/cancel", "/api/profile/retailer-extension/disconnect", "/api/profile/flipkart-extension/cancel", "/api/profile/flipkart-extension/disconnect"}:
                self._portal_extension_request()
                user_id = self._require_user()["id"]
                is_legacy = path.startswith("/api/profile/flipkart-extension/")
                if (is_legacy and payload) or (not is_legacy and set(payload) != {"provider"}):
                    raise ApiError("Retailer sync request is invalid", 400)
                provider = "flipkart" if is_legacy else payload["provider"]
                (disconnect_retailer_extension if path.endswith("disconnect") else cancel_retailer_extension)(user_id, provider)
                self._send(200, {"success": True})
                return
            if path == "/api/profile/gmail/sync":
                self._send(202, {"connection": start_gmail_sync(self._require_user()["id"])})
                return
            if path == "/api/profile/gmail/cancel":
                self._send(200, {"connection": cancel_gmail_sync(self._require_user()["id"])})
                return
            if path == "/api/profile/gmail/disconnect":
                self._send(200, {"connection": disconnect_gmail(self._require_user()["id"])})
                return
            if path in {"/api/profile/connections/cancel", "/api/profile/connections/disconnect"}:
                user_id = self._profile_user_id()
                self._local_connector_request()
                provider = str(payload.get("provider") or "").strip()
                (disconnect if path.endswith("disconnect") else cancel_sync)(user_id,provider)
                self._send(200, {"success":True})
                return
            if path == "/api/profile/memories/reindex":
                user_id = self._profile_user_id()
                self._send(200, {"memories": reindex_memories(user_id)})
                refresh_profile(user_id)
                return
            if path == "/api/profile/memories/remove":
                user_id = self._profile_user_id()
                memory_id = str(payload.get("id") or "")
                if not db.delete_taste_memory(user_id,memory_id):
                    raise ApiError("Memory not found",404)
                refresh_profile(user_id)
                self._send(200,{"success":True})
                return
            if path == "/api/profile/memories":
                user_id = self._profile_user_id()
                product = payload.get("product")
                if not isinstance(product,dict) or not isinstance(product.get("name"),str) or not product["name"].strip():
                    raise ApiError("A named product is required",400)
                from hashlib import sha256
                url = str(product.get("url") or "").strip()
                from backend.social import _public_reference_url
                _, safe_url = _public_reference_url(url)
                attributes = {key:str(product[key])[:500] for key in ("name","brand","category","color","size") if product.get(key)}
                memory = save_memories(user_id,[{"source_key":"like:"+sha256(safe_url.encode()).hexdigest(),"kind":"liked_product",
                                       "source_url":safe_url,"document":". ".join(attributes.values()),"attributes":attributes}])[0]
                refresh_profile(user_id)
                self._send(201,{"memory":memory})
                return
            if path == "/api/auth/logout":
                logout(self.headers.get("Cookie"))
                self._send(200, {"ok": True}, {"Set-Cookie": clear_session_cookie()})
                return
            if path == "/api/voice/warm":
                self._send(200, VoiceService().warm())
                return
            if path == "/api/voice/transcribe":
                voice = VoiceService()
                if voice.preference == "slng":
                    if not voice.slng_api_key:
                        raise VoiceError("SLNG_API_KEY is required for SLNG voice transcription.")
                    admission_error = _admit_paid_voice_request(self.client_address[0])
                    if admission_error:
                        raise ApiError("Voice request limit reached; try again shortly.", admission_error)
                    voice_request_admitted = True
                text = voice.transcribe(payload.get("audio"), payload.get("content_type"))
                provider_name = "slng" if voice.preference == "slng" else voice.stt_provider
                self._send(200, {"text": text, "provider": provider_name, "local": provider_name != "slng"})
                return
            if path == "/api/voice/speak":
                voice = VoiceService()
                if voice.provider == "browser":
                    self._send(200, {"provider": "browser", "text": str(payload.get("text") or "")[:1800]})
                    return
                if voice.provider in {"elevenlabs", "slng"}:
                    if voice.provider == "slng" and not voice.status()["configured"]:
                        raise VoiceError("SLNG_API_KEY is required when VOICE_PROVIDER=slng.")
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
            if path == "/api/voice/transcribe":
                print(json.dumps({"event": "voice_transcription_failed", "format": str(payload.get("content_type", ""))[:60], "error_class": type(error.__cause__).__name__, "provider_status": getattr(error.__cause__, "code", None)}), flush=True)
            self._send(503, {"error": str(error)})
        except ApiError as error:
            self._send(error.status, {"error": str(error)})
        except OrderError as error:
            self._send(400, {"error": str(error)})
        except PaymentError as error:
            self._send(error.status, {"error": str(error)})
        except GmailSyncError as error:
            self._send(409, {"error": str(error)})
        except ValueError as error:
            self._send(400, {"error": str(error)})
        except RuntimeError as error:
            self._send(503, {"error": str(error)})
        except Exception:
            self._send(500, {"error": "Internal server error"})
        finally:
            if search_request_admitted:
                _SEARCH_REQUEST_CAPACITY.release()
            if social_request_admitted:
                _SOCIAL_CAPACITY.release()
            if voice_request_admitted:
                _VOICE_CAPACITY.release()


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server = BoundedThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as err:
        if err.errno == 48:
            print(f"[artha] ❌ Error: Port {PORT} is already in use by another process.", file=sys.stderr)
            print(f"[artha] Run: lsof -ti :{PORT} | xargs kill -9", file=sys.stderr)
        raise
    print(f"Artha API listening on http://{HOST}:{PORT}")
    print("Google OAuth, live search configuration, provider routing, and voice status are ready.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Artha API")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
