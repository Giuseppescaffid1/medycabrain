"""
The claude.ai OAuth handshake (mcp_bridge/oauth_shim.py), driven through the
real ASGI app from build_app() with Starlette's TestClient (lifespan on, so
the MCP endpoint behind the secret really answers).

The point of the shim is that claude.ai can finish its connect flow while the
secret path stays the only key, so the tests check both halves: the flow works
end to end, and /<secret>/mcp behaves exactly as before.
"""

from __future__ import annotations

import base64
import hashlib
import json
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase
from starlette.testclient import TestClient

from mcp_bridge import oauth_shim, server

SECRET = "s3cret-segment"
BASE = "https://mcp.test"
CB = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "1"}}}
MCP_HEADERS = {"accept": "application/json, text/event-stream",
               "content-type": "application/json"}


class OAuthShimTests(SimpleTestCase):
    def setUp(self):
        for p in (mock.patch.object(server, "MCP_SECRET", SECRET),
                  mock.patch.object(server, "MCP_PUBLIC_URL", BASE),
                  mock.patch.dict("os.environ", {"MCP_OAUTH_REDIRECTS": ""})):
            p.start()
            self.addCleanup(p.stop)
        client = TestClient(server.build_app(), base_url=BASE,
                            follow_redirects=False)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.c = client

    def _code(self, **over):
        q = {"response_type": "code", "client_id": "cid", "redirect_uri": CB,
             "state": "st&1", "code_challenge": CHALLENGE,
             "code_challenge_method": "S256"}
        q.update(over)
        r = self.c.get("/authorize", params=q)
        return r, (parse_qs(urlsplit(r.headers["location"]).query)
                   if r.status_code == 302 else {})

    def _exchange(self, code, verifier=VERIFIER, ru=CB):
        return self.c.post("/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": ru, "code_verifier": verifier})

    # metadata
    def test_protected_resource_right_secret(self):
        for suffix in ("/mcp", ""):
            r = self.c.get(f"/.well-known/oauth-protected-resource/{SECRET}{suffix}")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {
                "resource": f"{BASE}/{SECRET}/mcp",
                "authorization_servers": [BASE],
                "bearer_methods_supported": ["header"]})
            self.assertEqual(r.headers["access-control-allow-origin"], "*")

    def test_protected_resource_wrong_secret_and_bare_are_404(self):
        self.assertEqual(self.c.get(
            "/.well-known/oauth-protected-resource/nope/mcp").status_code, 404)
        self.assertEqual(self.c.get(
            "/.well-known/oauth-protected-resource").status_code, 404)

    def test_auth_server_metadata_has_no_secret(self):
        for path in ("/.well-known/oauth-authorization-server",
                     "/.well-known/openid-configuration"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["registration_endpoint"], f"{BASE}/register")
            self.assertEqual(r.json()["code_challenge_methods_supported"], ["S256"])
            self.assertNotIn(SECRET, r.text)

    # register
    def test_register_ok(self):
        r = self.c.post("/register", json={"redirect_uris": [CB],
                                           "client_name": "claude"})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(body["client_id"])
        self.assertEqual(body["redirect_uris"], [CB])
        self.assertEqual(body["token_endpoint_auth_method"], "none")

    def test_register_bad_redirect(self):
        r = self.c.post("/register", json={"redirect_uris": ["https://evil.example/cb"]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "invalid_redirect_uri"})

    def test_extra_redirect_from_env(self):
        with mock.patch.dict("os.environ",
                             {"MCP_OAUTH_REDIRECTS": "https://x.test/cb"}):
            r = self.c.post("/register", json={"redirect_uris": ["https://x.test/cb"]})
        self.assertEqual(r.status_code, 201)

    # authorize + token
    def test_authorize_redirects_with_code_and_state(self):
        r, q = self._code()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["location"].startswith(CB + "?"))
        self.assertEqual(q["state"], ["st&1"])
        self.assertIn("code", q)

    def test_authorize_refuses_bad_requests_without_redirect(self):
        for over in ({"redirect_uri": "https://evil.example/cb"},
                     {"response_type": "token"},
                     {"code_challenge_method": "plain"},
                     {"code_challenge": ""}):
            r, _ = self._code(**over)
            self.assertEqual(r.status_code, 400, over)
            self.assertNotIn("location", r.headers)

    def test_full_flow_and_refresh(self):
        _, q = self._code()
        r = self._exchange(q["code"][0])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")
        body = r.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 2592000)
        r2 = self.c.post("/token", data={"grant_type": "refresh_token",
                                         "refresh_token": body["refresh_token"]})
        self.assertEqual(r2.status_code, 200)
        self.assertIn("access_token", r2.json())

    def test_wrong_verifier_is_invalid_grant(self):
        _, q = self._code()
        r = self._exchange(q["code"][0], verifier="x" * 50)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "invalid_grant"})

    def test_wrong_redirect_is_invalid_grant(self):
        _, q = self._code()
        self.assertEqual(self._exchange(
            q["code"][0], ru="https://claude.com/api/mcp/auth_callback"
        ).json(), {"error": "invalid_grant"})

    def test_tampered_and_expired_code_are_invalid_grant(self):
        _, q = self._code()
        code = q["code"][0]
        body, mac = code.split(".")
        forged = base64.urlsafe_b64encode(json.dumps(
            {"typ": "code", "cid": "cid", "ru": CB, "cc": CHALLENGE,
             "exp": 9999999999}).encode()).rstrip(b"=").decode() + "." + mac
        self.assertEqual(self._exchange(forged).json(), {"error": "invalid_grant"})
        expired = oauth_shim._sign(SECRET, {"typ": "code", "cid": "cid",
                                            "ru": CB, "cc": CHALLENGE, "exp": 1})
        self.assertEqual(self._exchange(expired).json(), {"error": "invalid_grant"})

    def test_access_token_is_not_a_refresh_token(self):
        _, q = self._code()
        access = self._exchange(q["code"][0]).json()["access_token"]
        r = self.c.post("/token", data={"grant_type": "refresh_token",
                                        "refresh_token": access})
        self.assertEqual(r.json(), {"error": "invalid_grant"})

    def test_unsupported_grant(self):
        r = self.c.post("/token", data={"grant_type": "password"})
        self.assertEqual(r.json(), {"error": "unsupported_grant_type"})

    def test_cors_preflight(self):
        r = self.c.options("/token")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers["access-control-allow-origin"], "*")
        self.assertIn("mcp-protocol-version",
                      r.headers["access-control-allow-headers"])

    # the rest is as before
    def test_mcp_still_works_with_and_without_authorization(self):
        for extra in ({}, {"authorization": "Bearer whatever"}):
            r = self.c.post(f"/{SECRET}/mcp", json=INIT,
                            headers={**MCP_HEADERS, **extra})
            self.assertEqual(r.status_code, 200, extra)

    def test_unknown_paths_still_404(self):
        self.assertEqual(self.c.get("/whatever").status_code, 404)
        self.assertEqual(self.c.post("/nope/mcp", json=INIT,
                                     headers=MCP_HEADERS).status_code, 404)
