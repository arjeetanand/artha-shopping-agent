"""Offline contract checks for Google OAuth state, PKCE, and redirect safety."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="artha-auth-", dir="/private/tmp") as directory:
        os.environ.update(
            {
                "SHOPPINGHELP_DB_PATH": str(Path(directory) / "auth.sqlite3"),
                "APP_ENV": "development",
                "GOOGLE_CLIENT_ID": "client-id",
                "GOOGLE_CLIENT_SECRET": "client-secret",
                "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/api/auth/google/callback",
                "SHOPPINGHELP_APP_URL": "http://127.0.0.1:5173",
            }
        )
        from backend.auth import begin_google_auth, google_configured
        from backend.db import db

        assert google_configured() is True
        redirect = begin_google_auth("/plans", "http://127.0.0.1:5173")
        query = parse_qs(urlparse(redirect).query)
        assert query["client_id"] == ["client-id"]
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) >= 40
        saved = db.consume_oauth_state(query["state"][0])
        assert saved and saved["next_path"] == "http://127.0.0.1:5173/plans"
        unsafe = begin_google_auth("https://evil.example/steal", "http://127.0.0.1:5173")
        unsafe_state = parse_qs(urlparse(unsafe).query)["state"][0]
        assert db.consume_oauth_state(unsafe_state)["next_path"] == "http://127.0.0.1:5173/"
        print("auth_contract_ok")


if __name__ == "__main__":
    main()
