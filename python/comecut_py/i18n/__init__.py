"""Tiny i18n helper — loads ``locales/*.json`` as flat ``key → text`` maps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_LOCALES_DIR = Path(__file__).parent / "locales"
_CACHE: dict[str, dict[str, Any]] = {}
_CURRENT: str = "en"


def available_locales() -> list[str]:
    return sorted(p.stem for p in _LOCALES_DIR.glob("*.json"))


def set_locale(code: str) -> None:
    global _CURRENT
    if code not in available_locales():
        raise ValueError(f"Unknown locale: {code!r}. Available: {available_locales()}")
    _CURRENT = code


def current_locale() -> str:
    return _CURRENT


def _load(code: str) -> dict[str, Any]:
    if code not in _CACHE:
        path = _LOCALES_DIR / f"{code}.json"
        _CACHE[code] = json.loads(path.read_text(encoding="utf-8"))
    return _CACHE[code]


def t(key: str, *, default: str | None = None) -> str:
    """Translate ``key`` into the current locale, falling back to English, then ``default``/``key``."""
    try:
        val = _load(_CURRENT).get(key)
    except FileNotFoundError:
        val = None
    if val is None and _CURRENT != "en":
        val = _load("en").get(key)
    if val is None:
        return default if default is not None else key
    return str(val)


__all__ = ["available_locales", "current_locale", "set_locale", "t"]
