"""Small, dependency-free settings loader for local and deployed Artha runs."""

from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOADED = False


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env() -> None:
    """Load the project .env once without overriding deployment environment vars."""
    global _LOADED
    if _LOADED or not ENV_PATH.exists():
        _LOADED = True
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if _ENV_KEY.match(key):
            os.environ.setdefault(key, _clean_env_value(value))
    _LOADED = True


def setting(name: str, default: str = "") -> str:
    load_env()
    return os.environ.get(name, default).strip()


def is_production() -> bool:
    return setting("APP_ENV", "development").lower() in {"production", "prod"}


load_env()
