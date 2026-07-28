"""
core/external_ref.py
====================
Reading a web page the user pastes into the chat, safely.

The chat can only answer from what it has indexed. The client's real question
is comparative — "look at this page and tell me what our material is missing"
— which needs a source that is deliberately NOT ours, read once, for one
conversation, and never mixed into the knowledge bank.

Why this is not just requests.get
---------------------------------
The URL comes from whoever is typing. A bare fetch turns this server into a
way of reaching things only it can reach: other services on the host, the
private network, the cloud metadata endpoint on 169.254.169.254. So the host
is resolved and every address it maps to is checked before we connect, and
redirects are followed by hand so each hop is checked too.

The check happens before the connection, so a name that resolves differently
a moment later would slip past (DNS rebinding). Closing that properly means
pinning the connection to the address we validated; it is not done here, and
is the one hole worth knowing about.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MAX_BYTES = 3_000_000      # a page, not a download
MAX_REDIRECTS = 3
TIMEOUT = 20
MAX_TEXT = 60_000          # what we keep after extraction


class RefusedURL(ValueError):
    """The url is not one this server will fetch."""


def _check_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RefusedURL("Sono ammessi solo indirizzi http e https.")
    host = parsed.hostname
    if not host:
        raise RefusedURL("Indirizzo senza nome host.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise RefusedURL(f"Nome host non risolvibile: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # Anything not routable on the public internet is off limits: it can
        # only be something this server reaches and the user cannot.
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise RefusedURL(
                "Questo indirizzo punta alla rete interna del server, "
                "non a una pagina pubblica."
            )


def _get(url: str) -> str:
    """Fetch with every redirect hop validated, and a hard size ceiling."""
    seen = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(seen)
        resp = requests.get(seen, headers={"User-Agent": _UA}, timeout=TIMEOUT,
                            allow_redirects=False, stream=True)
        if resp.is_redirect or resp.is_permanent_redirect:
            nxt = resp.headers.get("Location")
            resp.close()
            if not nxt:
                raise RefusedURL("Reindirizzamento senza destinazione.")
            seen = requests.compat.urljoin(seen, nxt)
            continue
        if resp.status_code != 200:
            resp.close()
            raise RefusedURL(f"La pagina ha risposto {resp.status_code}.")
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            resp.close()
            raise RefusedURL(f"Il contenuto non è una pagina web ({ctype.split(';')[0]}).")
        chunks, total = [], 0
        for chunk in resp.iter_content(64 * 1024, decode_unicode=False):
            total += len(chunk)
            if total > MAX_BYTES:
                resp.close()
                raise RefusedURL("La pagina è troppo grande da leggere.")
            chunks.append(chunk)
        resp.close()
        raw = b"".join(chunks)
        return raw.decode(resp.encoding or "utf-8", errors="replace")
    raise RefusedURL("Troppi reindirizzamenti.")


def fetch_reference(url: str) -> dict:
    """{url, title, text} for a public web page. Raises RefusedURL."""
    html = _get(url)
    import trafilatura

    text = trafilatura.extract(
        html, favor_precision=True, include_links=False, include_images=False,
    ) or ""
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) < 120:
        raise RefusedURL(
            "Non sono riuscito a estrarre testo leggibile da questa pagina."
        )
    title = ""
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            title = meta.title.strip()
    except Exception:  # noqa: BLE001 — the title is a nicety
        pass
    return {"url": url, "title": title or urlparse(url).netloc,
            "text": text[:MAX_TEXT]}
