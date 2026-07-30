"""
mcp_bridge/server.py
====================
The knowledge bank as an MCP server — so the client can add it to their own
Claude (claude.ai → Impostazioni → Connettori → connettore personalizzato)
and ask questions grounded in THEIR data: Medyca's reels, the competitors',
and the blogs.

Read-only by construction: every tool is a query. The client's Claude does
the reasoning; we hand it the same retrieval the in-app chat uses
(core.knowledge.semantic_search — hybrid ranking, per-side quotas), so both
surfaces answer from identical ground.

Auth: claude.ai custom connectors need a public HTTPS URL and offer OAuth or
nothing. Full OAuth (authorization server + dynamic client registration) is
out of proportion for one client, so the credential IS the URL: a random
secret path segment, checked here, rotatable by editing .env (MCP_SECRET)
and restarting. The trade-off is documented in docs/mcp-connettore-claude.md
— whoever has the URL has read access, treat it like a password.

Runs as its own service (uvicorn on 127.0.0.1:8020, systemd
medycabrain-mcp) behind messtudent.com's existing HTTPS. Django is set up
in-process for ORM access; this shares the backend's models but not its
gunicorn workers, so a slow MCP call cannot occupy an app slot.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402

MCP_SECRET = os.environ.get("MCP_SECRET", "")

server = MCPServer(
    name="Medyca Content Intelligence",
    instructions=(
        "Banca dati dei contenuti di Medyca (menopausa, terapie ormonali "
        "bioidentiche): i reel Instagram di @medyca.menopausa, i reel dei "
        "competitor monitorati, gli articoli del blog medyca.it e dei blog "
        "dei competitor. Tutte le analisi sono in italiano. Inizia con "
        "`panoramica` per sapere cosa contiene; usa `cerca` per trovare "
        "contenuti pertinenti e `leggi` per il testo completo di uno "
        "specifico contenuto. Cita sempre da quale contenuto (e di chi) "
        "viene un'affermazione: confondere ciò che dice Medyca con ciò che "
        "dicono i competitor è l'errore peggiore possibile."
    ),
)


def _hit(h: dict) -> dict:
    """A retrieval hit in the compact shape the client's Claude reads."""
    return {
        "id": f"{h['kind']}:{h['id']}",
        "tipo": "articolo" if h["kind"] == "blog" else "reel",
        "di": ("Medyca" if h.get("owner") != "competitor"
               else f"competitor: {h.get('account', '?')}"),
        "titolo": h.get("title") or "(senza titolo)",
        "estratto": h.get("snippet") or "",
        "url": h.get("url") or "",
        "pertinenza": h.get("score", 0),
    }


@server.tool(
    description=(
        "Cosa contiene la banca dati adesso: quanti reel e articoli per "
        "Medyca e per i competitor, quali fonti sono monitorate, quanti "
        "temi. Chiamala per prima: àncora i numeri prima di ragionare."
    )
)
def panoramica() -> dict:
    from django.db.models import Count

    from core.models import (BlogSource, ClusterRun, KnowledgeDocument, Reel,
                             TopicCluster, TrackedAccount)

    reels = dict(
        Reel.objects.filter(is_active=True)
        .values_list("account__owner_type").annotate(n=Count("id")))
    docs = dict(
        KnowledgeDocument.objects.filter(is_active=True, is_on_topic=True)
        .values_list("owner_type").annotate(n=Count("id")))
    return {
        "reel": {"medyca": reels.get("owned", 0),
                 "competitor": reels.get("competitor", 0)},
        "articoli": {"medyca": docs.get("owned", 0),
                     "competitor": docs.get("competitor", 0)},
        "account_instagram": list(
            TrackedAccount.objects.filter(is_active=True)
            .values_list("username", flat=True)),
        "blog_monitorati": list(
            BlogSource.objects.filter(is_active=True)
            .values_list("name", flat=True)),
        "temi_attuali": {
            run.scope: TopicCluster.objects.filter(run=run).count()
            for run in ClusterRun.objects.filter(is_current=True)
        },
        "nota": ("'medyca' = contenuti propri del cliente; 'competitor' = "
                 "contenuti altrui raccolti come ispirazione/confronto."),
    }


@server.tool(
    description=(
        "Ricerca semantica+lessicale su tutti i contenuti (trascrizioni dei "
        "reel, testi degli articoli, analisi). `scope`: 'all' | 'medyca' | "
        "'competitor'. `tipo`: 'tutti' | 'reel' | 'articolo'. Restituisce "
        "estratti con id da passare a `leggi` per il testo completo."
    )
)
def cerca(query: str, scope: str = "all", tipo: str = "tutti",
          limite: int = 8) -> list[dict]:
    from core.knowledge import semantic_search

    scope = scope if scope in ("all", "medyca", "competitor") else "all"
    limite = max(1, min(int(limite), 20))
    # Over-fetch when filtering by kind, so the filter does not starve.
    hits = semantic_search(query, top_k=limite * (2 if tipo != "tutti" else 1),
                           scope=scope)
    if tipo == "reel":
        hits = [h for h in hits if h["kind"] == "reel"]
    elif tipo == "articolo":
        hits = [h for h in hits if h["kind"] == "blog"]
    return [_hit(h) for h in hits[:limite]]


@server.tool(
    description=(
        "Il contenuto completo di un elemento trovato con `cerca`, dato il "
        "suo id ('reel:123' o 'blog:45'): trascrizione o testo integrale, "
        "analisi (tema, riassunto), affermazioni con citazione testuale."
    )
)
def leggi(id: str) -> dict:
    from core.models import KnowledgeDocument, Reel

    try:
        kind, pk = id.split(":", 1)
        pk = int(pk)
    except (ValueError, AttributeError):
        return {"errore": "id non valido: usa il formato 'reel:123' o 'blog:45'"}

    if kind == "reel":
        r = (Reel.objects.filter(id=pk, is_active=True)
             .select_related("account", "enrichment", "transcript").first())
        if not r:
            return {"errore": f"reel {pk} non trovato"}
        enr = getattr(r, "enrichment", None)
        tr = getattr(r, "transcript", None)
        return {
            "tipo": "reel",
            "di": ("Medyca" if r.account.owner_type == "owned"
                   else f"competitor: @{r.account.username}"),
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "pubblicato": r.posted_at.isoformat() if r.posted_at else None,
            "visualizzazioni": r.view_count, "like": r.like_count,
            "tema": enr.primary_topic if enr else "",
            "riassunto": enr.summary_it if enr else "",
            "argomenti": enr.topics if enr else [],
            "didascalia": r.caption,
            "trascrizione": (tr.text if tr else "")[:12000],
            "affermazioni": [
                {"testo": a.text_it, "citazione": a.quote}
                for a in r.arguments.all()[:10]
            ],
        }
    if kind == "blog":
        d = (KnowledgeDocument.objects.filter(id=pk, is_active=True)
             .select_related("source").first())
        if not d:
            return {"errore": f"articolo {pk} non trovato"}
        return {
            "tipo": "articolo",
            "di": ("Medyca" if d.owner_type == "owned"
                   else f"competitor: {d.source.name if d.source else '?'}"),
            "url": d.source_url,
            "pubblicato": d.published_at.isoformat() if d.published_at else None,
            "autore": d.author,
            "lingua": d.language or "it",
            "tema": d.primary_topic,
            "riassunto": d.summary_it,
            "argomenti": d.topics,
            # Plain text, not markdown: the claims' quotes are verified
            # against this exact text, and the client's Claude checking a
            # quote must find it verbatim in what it was given.
            "testo": (d.content_text or d.content_md)[:12000],
            "affermazioni": [
                {"testo": a.text_it, "citazione": a.quote}
                for a in d.arguments.all()[:10]
            ],
        }
    return {"errore": "tipo sconosciuto: usa 'reel' o 'blog'"}


@server.tool(
    description=(
        "La mappa dei temi correnti (clustering automatico dei contenuti). "
        "`scope`: 'medyca' per i temi dei contenuti di Medyca, 'competitor' "
        "per quelli del mercato. Ogni tema ha etichetta, dimensione e le "
        "affermazioni più ricorrenti — utile per capire copertura e buchi."
    )
)
def temi(scope: str = "competitor") -> list[dict]:
    from core.models import ArgumentAssignment, ClusterRun, TopicCluster

    owner = "owned" if scope in ("medyca", "owned") else "competitor"
    run = ClusterRun.objects.filter(scope=owner, is_current=True).first()
    if not run:
        return []
    out = []
    for c in TopicCluster.objects.filter(run=run).order_by("-size")[:40]:
        claims = (ArgumentAssignment.objects
                  .filter(run=run, cluster=c)
                  .select_related("argument")[:3])
        out.append({
            "id": c.id,
            "tema": c.label_it,
            "descrizione": c.description_it,
            "contenuti": c.size,
            "parole_chiave": c.keywords[:6],
            "esempi_affermazioni": [a.argument.text_it for a in claims],
        })
    return out


def build_app():
    """The ASGI app: secret path segment in front, MCP behind.

    Stateless + JSON responses: every claude.ai request carries the whole
    context, nothing here is worth a session store, and plain JSON keeps
    nginx buffering questions out of the picture entirely.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    # The SDK's DNS-rebinding guard is OFF, deliberately. It rejected
    # claude.ai's own client: Anthropic sends `Origin: https://claude.ai`,
    # and an allowed-hosts-only config 403s any request carrying an Origin —
    # measured, that was the whole "Couldn't connect to the server" failure.
    # The guard defends browser pages steering ambient credentials at a
    # local server; this endpoint has none of that: no cookies, auth is the
    # secret path segment, and nginx only routes the public hostname here.
    # Enumerating Anthropic's origins instead would break on their next
    # domain change, silently, for the client.
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    inner = server.streamable_http_app(json_response=True, stateless_http=True,
                                       transport_security=security)

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        if not MCP_SECRET:
            # Refusing to run open is the whole point of the wrapper.
            await _deny(send, 503, "MCP_SECRET non configurato")
            return
        path = scope.get("path", "")
        # The secret segment is compared with whitespace removed. Measured
        # failure mode (2026-07-30): the URL wrapped in a messenger, the
        # copy gained a space mid-secret ("v%20FZ5"), and claude.ai got 404
        # on every request while every server-side test passed. Whitespace
        # can never occur in a token_urlsafe secret, so stripping it only
        # forgives copy-paste damage — it accepts nothing an attacker
        # could not already send.
        parts = path.split("/", 2)
        candidate = "".join((parts[1] if len(parts) > 1 else "").split())
        if candidate == MCP_SECRET:
            rest = "/" + parts[2] if len(parts) > 2 else "/"
            scope = dict(scope)
            scope["path"] = rest
            return await inner(scope, receive, send)
        await _deny(send, 404, "not found")

    return app


async def _deny(send, status: int, msg: str):
    body = msg.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})


def _warm():
    """Load the embedder and the retrieval index at startup.

    Cold, the first `cerca` costs ~14s (sentence-transformers + 900 vectors
    off the DB). The client's very first question through their Claude is
    exactly the wrong moment to pay that.
    """
    try:
        from core.knowledge import _get_embedder, _load_index
        _get_embedder()
        _load_index("all")
    except Exception:  # noqa: BLE001 — warming is a courtesy, not a dependency
        pass


import threading  # noqa: E402

threading.Thread(target=_warm, daemon=True).start()

app = build_app()
