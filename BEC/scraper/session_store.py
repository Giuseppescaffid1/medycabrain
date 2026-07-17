"""
scraper/session_store.py
========================
Load / validate / back up the Instagram session cookies.

Cookies are exported once from a logged-in **burner** account browser
(Cookie-Editor extension → JSON export) into BEC/data/ig_session.json.
Supported input shapes:
  - Cookie-Editor / EditThisCookie array: [{"name","value",...}, ...]
  - a flat dict: {"sessionid": "...", "csrftoken": "...", ...}

Mirrors the load/validate/backup pattern from the SPI Facebook
cookie_manager.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

CRITICAL_COOKIES = ("sessionid", "csrftoken", "ds_user_id")


def _normalize(raw) -> dict:
    """Return a flat {name: value} cookie dict from either supported shape."""
    if isinstance(raw, dict):
        # Either already flat, or {"cookies": [...]}
        if "cookies" in raw and isinstance(raw["cookies"], list):
            raw = raw["cookies"]
        else:
            return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
    raise ValueError("Unrecognized cookie file format")


def load_cookies(path: str | None = None) -> dict:
    """Load cookies as a flat dict. Raises FileNotFoundError / ValueError."""
    from django.conf import settings

    path = path or settings.IG_SESSION_FILE
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"IG session file not found: {path}")
    with open(p, "r", encoding="utf-8") as fh:
        cookies = _normalize(json.load(fh))
    missing = [c for c in CRITICAL_COOKIES if c not in cookies]
    if missing:
        logger.warning("[ig-session] missing critical cookies: %s", missing)
    return cookies


def import_cookies(src_path: str, dest_path: str | None = None) -> dict:
    """Import + validate a cookie export, backing up any existing file first."""
    from django.conf import settings

    dest_path = dest_path or settings.IG_SESSION_FILE
    with open(src_path, "r", encoding="utf-8") as fh:
        cookies = _normalize(json.load(fh))
    missing = [c for c in CRITICAL_COOKIES if c not in cookies]
    if missing:
        raise ValueError(f"Cookie export missing critical cookies: {missing}")

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        backup = dest.with_suffix(dest.suffix + f".backup_{int(time.time())}")
        dest.replace(backup)
        logger.info("[ig-session] backed up old session → %s", backup)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(cookies, fh, indent=2)
    os.chmod(dest, 0o600)
    logger.info("[ig-session] imported %d cookies → %s", len(cookies), dest)
    return cookies


def test_session(path: str | None = None) -> tuple[bool, str]:
    """Live-check the session by hitting the current-user API.

    Returns (ok, detail). ok=True means the cookies authenticate.
    """
    try:
        cookies = load_cookies(path)
    except (FileNotFoundError, ValueError) as exc:
        return False, str(exc)

    from .ig_client import build_session, IG_HEADERS, TOPSEARCH_URL

    # current_user is a mobile-app endpoint (rejects the web UA with
    # "useragent mismatch"). Validate against the authenticated web
    # topsearch endpoint instead: a valid session returns JSON.
    session = build_session(cookies)
    try:
        resp = session.get(
            TOPSEARCH_URL,
            params={"query": "instagram", "context": "blended"},
            headers={**IG_HEADERS, "x-csrftoken": cookies.get("csrftoken", "")},
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"request failed: {exc!r}"

    ctype = resp.headers.get("content-type", "")
    if resp.status_code == 200 and "json" in ctype:
        try:
            n = len(resp.json().get("users", []))
            return True, f"authenticated (topsearch returned {n} users)"
        except Exception:  # noqa: BLE001
            return True, "authenticated (200 JSON)"
    if resp.status_code in (401, 403):
        return False, f"HTTP {resp.status_code} — cookies invalid/expired or checkpoint"
    return False, f"unexpected HTTP {resp.status_code} (ctype={ctype})"
