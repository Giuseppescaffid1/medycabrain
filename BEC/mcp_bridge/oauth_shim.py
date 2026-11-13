"""
mcp_bridge/oauth_shim.py
========================
A tiny OAuth 2.1 server that approves everybody, so claude.ai can "log in"
to the connector without anyone typing a password.

Why it exists. Until about November 2026 claude.ai added an authless custom
connector by calling POST /<secret>/mcp and nothing else. Then it changed
the connect flow: measured on 2026-11-13, a Connect attempt logged

    POST /<secret>/mcp                                        200
    GET  /.well-known/oauth-protected-resource/<secret>/mcp   404
    GET  /.well-known/oauth-protected-resource                404
    GET  /.well-known/oauth-authorization-server              404
    POST /register                                            404

and claude.ai showed "Couldn't register with medycabrain's sign-in
service". It now insists on the OAuth steps: find the metadata, register a
client (RFC 7591), authorize with PKCE, exchange the code for a token.

Security, in plain words. Nothing changes: the secret path segment is still
the only key. Whoever knows https://mcp.medyca.it/<secret>/mcp can read the
data, and whoever does not know it gets a 404 on the MCP endpoint. This
shim only lets claude.ai walk through the door it is already allowed
through. That is why:
  - there is no user, no password, no consent screen: /authorize approves
    at once;
  - the tokens are NOT checked on /<secret>/mcp. Requests with or without an
    Authorization header work exactly as before. Tokens exist only because
    claude.ai refuses to proceed without getting one;
  - the protected-resource metadata is served only for the URL that already
    contains the right secret (the bare /.well-known/oauth-protected-resource
    stays 404: it would have to put the secret in the body);
  - redirect URIs are limited to an allow-list (claude.ai and claude.com
    callbacks, plus MCP_OAUTH_REDIRECTS from .env), so no other site can use
    the shim to bounce a browser around.

Stateless: nothing is stored. Codes and tokens are base64url(JSON) + "." +
HMAC-SHA256 signed with MCP_SECRET, so rotating the secret invalidates every
code and token at once, with no database. Standard library only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

CODE_TTL = 300                      # seconds: a code is used within moments
TOKEN_TTL = 30 * 24 * 3600          # 2592000: one month, claude.ai refreshes
MAX_BODY = 64 * 1024

_DEFAULT_REDIRECTS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)

_CORS = [
    (b"access-control-allow-origin", b"*"),
]
_PREFLIGHT = _CORS + [
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-allow-headers",
     b"content-type, authorization, mcp-protocol-version"),
    (b"access-control-max-age", b"86400"),
]
_PROTECTED = "/.well-known/oauth-protected-resource/"
_ENDPOINTS = {"/.well-known/oauth-authorization-server",
              "/.well-known/openid-configuration",
              "/register", "/authorize", "/token"}


def allowed_redirects() -> set[str]:
    extra = os.environ.get("MCP_OAUTH_REDIRECTS", "")
    return set(_DEFAULT_REDIRECTS) | {u.strip() for u in extra.split(",")
                                      if u.strip()}


# ── signed, stateless codes and tokens ──────────────────────────────────

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def _verify(secret: str, token: str, typ: str, now: float | None = None):
    """The payload if signature, type and expiry are good, else None."""
    try:
        body, mac = token.split(".", 1)
        want = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("typ") != typ:
            return None
        if payload["exp"] < (time.time() if now is None else now):
            return None
        return payload
    except Exception:
        return None


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    return hmac.compare_digest(_b64(digest), challenge)


def _token_pair(secret: str, cid: str) -> dict:
    now = int(time.time())
    return {
        "access_token": _sign(secret, {"typ": "access", "cid": cid,
                                       "exp": now + TOKEN_TTL}),
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL,
        "refresh_token": _sign(secret, {"typ": "refresh", "cid": cid,
                                        "exp": now + 2 * TOKEN_TTL}),
    }


# ── pure endpoint logic: (status, headers, body) ────────────────────────

def _json(status: int, data: dict, extra=()):
    headers = [(b"content-type", b"application/json")] + _CORS + list(extra)
    return status, headers, json.dumps(data).encode()


def _text(status: int, text: str):
    return status, [(b"content-type", b"text/plain; charset=utf-8")], text.encode()


def protected_resource(path: str, secret: str, public_url: str):
    from mcp_bridge.server import _clean  # same copy-paste forgiveness
    seg = path[len(_PROTECTED):]
    if seg.endswith("/mcp"):
        seg = seg[:-4]
    if not seg or "/" in seg or _clean(seg) != secret:
        return _text(404, "not found")
    return _json(200, {"resource": f"{public_url}/{secret}/mcp",
                       "authorization_servers": [public_url],
                       "bearer_methods_supported": ["header"]})


def auth_server_metadata(public_url: str):
    return _json(200, {
        "issuer": public_url,
        "authorization_endpoint": f"{public_url}/authorize",
        "token_endpoint": f"{public_url}/token",
        "registration_endpoint": f"{public_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


def register(body: bytes):
    try:
        data = json.loads(body or b"{}")
        uris = data["redirect_uris"]
        assert isinstance(uris, list) and uris
    except Exception:
        return _json(400, {"error": "invalid_client_metadata"})
    if not all(isinstance(u, str) and u in allowed_redirects() for u in uris):
        return _json(400, {"error": "invalid_redirect_uri"})
    return _json(201, {
        "client_id": secrets.token_urlsafe(16),
        "client_id_issued_at": int(time.time()),
        "redirect_uris": uris,
        "client_name": data.get("client_name", ""),
        "grant_types": data.get("grant_types",
                                ["authorization_code", "refresh_token"]),
        "response_types": data.get("response_types", ["code"]),
        "token_endpoint_auth_method": "none",
    })


def authorize(query: str, secret: str):
    q = {k: v[0] for k, v in parse_qs(query).items()}
    ru = q.get("redirect_uri", "")
    # Bad redirect or request: plain 400, never a redirect to an unvetted URL.
    if ru not in allowed_redirects():
        return _text(400, "redirect_uri non ammesso")
    if q.get("response_type") != "code":
        return _text(400, "response_type deve essere code")
    if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        return _text(400, "serve PKCE con S256")
    code = _sign(secret, {"typ": "code", "cid": q.get("client_id", ""),
                          "ru": ru, "cc": q["code_challenge"],
                          "exp": int(time.time()) + CODE_TTL})
    parts = urlsplit(ru)
    params = parse_qsl(parts.query) + [("code", code)]
    if q.get("state"):
        params.append(("state", q["state"]))
    target = urlunsplit(parts._replace(query=urlencode(params)))
    return 302, [(b"location", target.encode()), (b"cache-control", b"no-store")], b""


def token(body: bytes, secret: str):
    nostore = [(b"cache-control", b"no-store")]
    f = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
    grant = f.get("grant_type")
    if grant == "authorization_code":
        p = _verify(secret, f.get("code", ""), "code")
        if (not p or p["ru"] != f.get("redirect_uri")
                or not f.get("code_verifier")
                or not _pkce_ok(f["code_verifier"], p["cc"])
                or (f.get("client_id") and f["client_id"] != p["cid"])):
            return _json(400, {"error": "invalid_grant"}, nostore)
        return _json(200, _token_pair(secret, p["cid"]), nostore)
    if grant == "refresh_token":
        p = _verify(secret, f.get("refresh_token", ""), "refresh")
        if not p:
            return _json(400, {"error": "invalid_grant"}, nostore)
        return _json(200, _token_pair(secret, p["cid"]), nostore)
    return _json(400, {"error": "unsupported_grant_type"}, nostore)


# ── ASGI glue ───────────────────────────────────────────────────────────

async def _read_body(receive) -> bytes | None:
    """The request body, or None if it passes MAX_BODY."""
    chunks, size = [], 0
    while True:
        msg = await receive()
        chunk = msg.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
        if not msg.get("more_body"):
            return b"".join(chunks)


def is_oauth_path(path: str) -> bool:
    return path in _ENDPOINTS or path.startswith(_PROTECTED)


async def handle(scope, receive, send, secret: str, public_url: str) -> bool:
    """Answer OAuth requests. False means "not mine": carry on as before."""
    path, method = scope.get("path", ""), scope.get("method", "GET")
    if not secret or not is_oauth_path(path):
        return False
    if method == "OPTIONS":
        status, headers, body = 204, _PREFLIGHT, b""
    elif path.startswith(_PROTECTED) and method == "GET":
        status, headers, body = protected_resource(path, secret, public_url)
    elif path in ("/.well-known/oauth-authorization-server",
                  "/.well-known/openid-configuration") and method == "GET":
        status, headers, body = auth_server_metadata(public_url)
    elif path == "/authorize" and method == "GET":
        status, headers, body = authorize(
            scope.get("query_string", b"").decode(), secret)
    elif path in ("/register", "/token") and method == "POST":
        raw = await _read_body(receive)
        if raw is None:
            status, headers, body = _text(413, "richiesta troppo grande")
        elif path == "/register":
            status, headers, body = register(raw)
        else:
            status, headers, body = token(raw, secret)
    else:
        status, headers, body = _text(404, "not found")
    await send({"type": "http.response.start", "status": status,
                "headers": headers + [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
    return True
