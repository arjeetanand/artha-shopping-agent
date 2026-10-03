"""Google OAuth and cookie-session helpers using only Python's standard library."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import CookieError, SimpleCookie
from typing import Any

from .db import db
from .settings import is_production, setting


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SESSION_COOKIE = "artha_session"


class AuthError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _google_config() -> tuple[str, str, str]:
    return (
        setting("GOOGLE_CLIENT_ID"),
        setting("GOOGLE_CLIENT_SECRET"),
        setting("GOOGLE_REDIRECT_URI"),
    )


def google_configured() -> bool:
    return all(_google_config())


def _safe_next(value: str | None) -> str:
    value = value or "/"
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        raise AuthError("The sign-in return path is invalid.")
    value = value.strip()
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _valid_oauth_state(state: str) -> bool:
    return len(state) == 43 and all(char.isascii() and (char.isalnum() or char in "-_") for char in state)


def _oauth_state_cookie_settings(state: str) -> tuple[str, str, bool]:
    if not _valid_oauth_state(state):
        raise ValueError("Invalid OAuth state")
    force_secure = setting("SHOPPINGHELP_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    secure = is_production() or force_secure
    prefix = "__Host-" if secure else ""
    path = "/" if secure else "/api/auth/google/callback"
    return f"{prefix}artha_oauth_state_{state}", path, secure


def oauth_state_cookie(state: str) -> str:
    name, path, secure = _oauth_state_cookie_settings(state)
    parts = [f"{name}={state}", f"Path={path}", "HttpOnly", "SameSite=Lax", "Max-Age=600"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_oauth_state_cookie(state: str) -> str | None:
    if not _valid_oauth_state(state):
        return None
    name, path, secure = _oauth_state_cookie_settings(state)
    parts = [f"{name}=", f"Path={path}", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def google_oauth_state_matches(cookie_header: str | None, state: str) -> bool:
    if not cookie_header or not _valid_oauth_state(state):
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except (CookieError, ValueError, TypeError):
        return False
    morsel = cookie.get(_oauth_state_cookie_settings(state)[0])
    return bool(morsel and secrets.compare_digest(morsel.value, state))


def _verifier() -> str:
    return secrets.token_urlsafe(64)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _return_target(next_path: str | None, app_origin: str | None) -> str:
    default = app_redirect_url(_safe_next(next_path))
    if not app_origin:
        return default
    parsed = urllib.parse.urlparse(app_origin)
    is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or (is_production() and app_origin.rstrip("/") != setting("SHOPPINGHELP_APP_URL", "").rstrip("/")) or (not is_production() and not is_loopback):
        return default
    return f"{parsed.scheme}://{parsed.netloc}{_safe_next(next_path)}"


def begin_google_auth(next_path: str | None = None, app_origin: str | None = None) -> str:
    client_id, _, redirect_uri = _google_config()
    if not all((client_id, redirect_uri)):
        raise AuthError("Google sign-in is not configured on this server.", 503)
    state = secrets.token_urlsafe(32)
    verifier = _verifier()
    db.save_oauth_state(state, verifier, _return_target(next_path, app_origin))
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _post_form_json(url: str, payload: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_userinfo(access_token: str) -> dict[str, Any]:
    request = urllib.request.Request(GOOGLE_USERINFO_URL, headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def complete_google_auth(code: str, state: str, cookie_header: str | None) -> tuple[dict[str, Any], str, str]:
    if not code or not state:
        raise AuthError("Google did not return a complete authorization response.")
    if not google_oauth_state_matches(cookie_header, state):
        raise AuthError("Your sign-in request could not be validated. Please start Google sign-in again.")
    oauth_state = db.consume_oauth_state(state)
    if not oauth_state:
        raise AuthError("Your sign-in request expired. Please start Google sign-in again.")
    client_id, client_secret, redirect_uri = _google_config()
    if not all((client_id, client_secret, redirect_uri)):
        raise AuthError("Google sign-in is not configured on this server.", 503)
    try:
        tokens = _post_form_json(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": oauth_state["code_verifier"],
            },
        )
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            raise AuthError("Google did not issue an access token.")
        profile = _get_userinfo(access_token)
    except AuthError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as error:
        raise AuthError("Google could not complete sign-in. Check the redirect URI and consent screen configuration.") from error

    google_sub = str(profile.get("sub") or "").strip()
    email = str(profile.get("email") or "").strip().lower()
    verified = profile.get("email_verified")
    if not google_sub or not email or verified not in {True, "true", "True", 1, "1"}:
        raise AuthError("Google did not return a verified account email.")
    user = db.upsert_google_user(
        google_sub=google_sub,
        email=email,
        name=str(profile.get("name") or email.split("@", 1)[0]).strip()[:120],
        picture=str(profile.get("picture") or "").strip()[:1000],
    )
    session_token = db.create_session(user["id"])
    return user, session_token, oauth_state["next_path"]


def current_user(cookie_header: str | None) -> dict[str, Any] | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except (ValueError, TypeError):
        return None
    morsel = cookie.get(SESSION_COOKIE)
    return db.get_user_for_session(morsel.value) if morsel else None


def logout(cookie_header: str | None) -> None:
    if not cookie_header:
        return
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except (ValueError, TypeError):
        return
    morsel = cookie.get(SESSION_COOKIE)
    if morsel:
        db.delete_session(morsel.value)


def session_cookie(session_token: str) -> str:
    parts = [f"{SESSION_COOKIE}={session_token}", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=604800"]
    secure_override = setting("SHOPPINGHELP_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    if is_production() or secure_override:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie() -> str:
    parts = [f"{SESSION_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    secure_override = setting("SHOPPINGHELP_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    if is_production() or secure_override:
        parts.append("Secure")
    return "; ".join(parts)


def app_redirect_url(next_path: str) -> str:
    base = setting("SHOPPINGHELP_APP_URL", "http://127.0.0.1:5173").rstrip("/")
    return f"{base}{_safe_next(next_path)}"
