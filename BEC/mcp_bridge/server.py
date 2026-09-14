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
MCP_INVITE = os.environ.get("MCP_INVITE", "")

server = MCPServer(
    name="Medyca Content Intelligence",
    instructions=(
        "Banca dati dei contenuti di Medyca (menopausa, terapie ormonali "
        "bioidentiche). Contiene DUE tipi di materiale, tenuti separati "
        "perché rispondono a domande diverse:\n"
        "• REEL Instagram (video) — di Medyca e dei competitor: "
        "`cerca_reel`, `leggi_reel`. Hanno trascrizione, gancio iniziale, "
        "formato del video e numeri di pubblico.\n"
        "• ARTICOLI di blog — di Medyca e dei competitor: `cerca_articoli`, "
        "`leggi_articolo`, `fonti_blog`. Hanno testo integrale, autore, "
        "data e lingua; non hanno gancio né formato, che sono cose da video.\n"
        "Usa lo strumento del tipo che ti serve. `cerca_tutto` e `leggi` "
        "esistono per le domande che attraversano i due mondi, ma quando la "
        "domanda riguarda solo i video o solo gli articoli lo strumento "
        "specifico dà risposte più pulite.\n"
        "Inizia con `panoramica` per sapere cosa c'è dentro; `temi` per la "
        "mappa degli argomenti. Tutte le analisi sono in italiano.\n"
        "Cita sempre da quale contenuto (e di chi) viene un'affermazione: "
        "confondere ciò che dice Medyca con ciò che dicono i competitor è "
        "l'errore peggiore possibile."
    ),
)


def _hit(h: dict) -> dict:
    """A retrieval hit in the compact shape the client's Claude reads."""
    return {
        "id": f"{h['kind']}:{h['id']}",
        # "articolo" would be a small lie for a TV episode the client keeps as
        # reference: the type is what Claude uses to decide how to cite it.
        "tipo": ("materiale di riferimento" if h.get("inspiration")
                 else "articolo" if h["kind"] == "blog" else "reel"),
        "di": ("Medyca" if h.get("owner") != "competitor"
               else f"competitor: {h.get('account', '?')}"),
        "titolo": h.get("title") or "(senza titolo)",
        "estratto": h.get("snippet") or "",
        "url": h.get("url") or "",
        "ispirazione": bool(h.get("inspiration")),
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
    # Counted apart from "articoli": these are videos the client added as
    # reference, and folding them into the article totals would quietly
    # inflate the numbers every answer is anchored on.
    rif = KnowledgeDocument.objects.filter(is_active=True, is_inspiration=True)
    return {
        "reel": {"medyca": reels.get("owned", 0),
                 "competitor": reels.get("competitor", 0)},
        "articoli": {"medyca": docs.get("owned", 0),
                     "competitor": docs.get("competitor", 0)},
        "materiale_di_riferimento": {
            "totale": rif.count(),
            "con_trascrizione": rif.exclude(content_text="").count(),
            "solo_link": rif.filter(content_text="").count(),
        },
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
                 "contenuti altrui raccolti come ispirazione/confronto. "
                 "'materiale_di_riferimento' sono video e interventi che il "
                 "cliente ha aggiunto apposta (vedi `cerca_riferimenti`): "
                 "quelli 'solo_link' non hanno trascrizione, quindi se ne "
                 "conosce il titolo e la fonte, non il contenuto."),
    }


def _search(query: str, scope: str, limite: int, only: str | None,
            only_inspiration: bool = False) -> list[dict]:
    """Shared retrieval for every search tool.

    One implementation on purpose: the typed tools differ only in which side
    of the corpus they keep, so they can never drift into ranking the same
    question differently. `only` is "reel", "blog", or None for both.

    When filtering, the pool is over-fetched so the filter does not starve —
    asking for 8 articles out of a pool of 8 mixed hits would return two.
    rerank=True gives the client's Claude the same LLM-sharpened order the
    in-app chat gets.
    """
    from core.knowledge import semantic_search

    scope = scope if scope in ("all", "medyca", "competitor") else "all"
    limite = max(1, min(int(limite), 20))
    hits = semantic_search(query, top_k=limite * (3 if only else 1),
                           scope=scope, rerank=True,
                           only_inspiration=only_inspiration)
    if only:
        hits = [h for h in hits if h["kind"] == only]
    return [_hit(h) for h in hits[:limite]]


@server.tool(
    description=(
        "Cerca SOLO tra i reel Instagram (video), di Medyca e dei "
        "competitor. Cerca nelle trascrizioni, nelle didascalie e "
        "nell'analisi. `scope`: 'all' | 'medyca' | 'competitor'. "
        "Restituisce estratti con id 'reel:123' da passare a `leggi_reel`. "
        "Usa questo — non `cerca_articoli` — per domande su come si parla a "
        "voce, sui ganci iniziali, sul formato dei video o sul pubblico."
    )
)
def cerca_reel(query: str, scope: str = "all", limite: int = 8) -> list[dict]:
    return _search(query, scope, limite, only="reel")


@server.tool(
    description=(
        "Cerca SOLO tra gli articoli di blog, di Medyca e dei competitor. "
        "Cerca nel testo integrale e nell'analisi. `scope`: 'all' | "
        "'medyca' | 'competitor'. Restituisce estratti con id 'blog:45' da "
        "passare a `leggi_articolo`. Usa questo — non `cerca_reel` — per "
        "domande su cosa è scritto, su fonti e affermazioni documentate, o "
        "per confrontare la copertura editoriale scritta."
    )
)
def cerca_articoli(query: str, scope: str = "all", limite: int = 8) -> list[dict]:
    return _search(query, scope, limite, only="blog")


@server.tool(
    description=(
        "Cerca in TUTTO: reel e articoli insieme, ordinati per pertinenza. "
        "Usalo solo quando la domanda attraversa i due mondi (per esempio "
        "'di cosa parla Medyca su questo tema, ovunque'). Se ti interessa un "
        "tipo solo, `cerca_reel` o `cerca_articoli` danno risposte più "
        "pulite. Ogni risultato dichiara il proprio 'tipo'."
    )
)
def cerca_tutto(query: str, scope: str = "all", limite: int = 8) -> list[dict]:
    return _search(query, scope, limite, only=None)


def _parse_id(id: str, atteso: str | None = None) -> tuple[str, int] | dict:
    """('reel', 123) from 'reel:123', or an error dict the tool returns as is.

    A bare number is accepted when the tool already knows the type: the
    client's Claude routinely passes `leggi_reel("123")`, and refusing it
    would be pedantry rather than safety.
    """
    raw = str(id).strip()
    if atteso and raw.isdigit():
        return atteso, int(raw)
    try:
        kind, pk = raw.split(":", 1)
        pk = int(pk)
    except (ValueError, AttributeError):
        return {"errore": "id non valido: usa il formato 'reel:123' o 'blog:45'"}
    if atteso and kind != atteso:
        nome = "reel" if atteso == "reel" else "articolo"
        altro = "leggi_articolo" if atteso == "reel" else "leggi_reel"
        return {"errore": f"questo id non è un {nome}: usa {altro}"}
    return kind, pk


def _leggi_reel(pk: int) -> dict:
    from core.models import Reel

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
        # Video-only fields: an article has no spoken opening and no format.
        "gancio": enr.hook_text if enr else "",
        "analisi_gancio": enr.hook_analysis_it if enr else "",
        "formato": enr.content_format if enr else "",
        "pubblico": enr.target_audience_it if enr else "",
        "didascalia": r.caption,
        "trascrizione": (tr.text if tr else "")[:12000],
        "affermazioni": [
            {"testo": a.text_it, "citazione": a.quote}
            for a in r.arguments.all()[:10]
        ],
    }


def _leggi_articolo(pk: int) -> dict:
    from core.models import KnowledgeDocument

    d = (KnowledgeDocument.objects.filter(id=pk, is_active=True)
         .select_related("source").first())
    if not d:
        return {"errore": f"articolo {pk} non trovato"}
    testo = (d.content_text or d.content_md)[:12000]
    return {
        "tipo": "video di riferimento" if d.source_type == "video" else "articolo",
        "di": ("Medyca" if d.owner_type == "owned"
               else f"competitor: {d.source.name if d.source else (d.author or '?')}"),
        "ispirazione": d.is_inspiration,
        # Said plainly rather than left to be inferred from an empty string:
        # a video whose audio could not be fetched is a reference, not a
        # source you can quote from.
        "trascrizione_disponibile": bool(testo.strip()),
        "nota": ("" if testo.strip() else
                 "Di questo video abbiamo solo titolo e link: nessuna "
                 "trascrizione, quindi non attribuirgli affermazioni."),
        "fonte": d.source.name if d.source else (d.author or ""),
        "url": d.source_url,
        "pubblicato": d.published_at.isoformat() if d.published_at else None,
        "autore": d.author,
        "lingua": d.language or "it",
        "tema": d.primary_topic,
        "riassunto": d.summary_it,
        "argomenti": d.topics,
        # For material the client added on purpose, "in_tema: false" is
        # expected, not a defect: the verdict is given against a
        # menopause-centred prompt and this shelf is deliberately wider. Said
        # raw, it reads as "ignore this" and would make Claude discard the
        # very sources the client chose. Ownership of the judgement stays
        # visible, but framed for what it is.
        **({"in_tema": d.is_on_topic, "fuori_tema_perche": d.off_topic_reason}
           if not d.is_inspiration else
           {"in_tema": True,
            "perimetro": (
                "Materiale di riferimento scelto dal cliente: tratta "
                "argomenti vicini ma non necessariamente di menopausa "
                f"({d.off_topic_reason[:160]})" if d.off_topic_reason else
                "Materiale di riferimento scelto dal cliente.")}),
        # Plain text, not markdown: the claims' quotes are verified against
        # this exact text, and the client's Claude checking a quote must find
        # it verbatim in what it was given.
        "testo": testo,
        "affermazioni": [
            {"testo": a.text_it, "citazione": a.quote}
            for a in d.arguments.all()[:10]
        ],
    }


@server.tool(
    description=(
        "Il contenuto completo di UN REEL, dato il suo id ('reel:123' o "
        "solo '123'): trascrizione integrale, didascalia, tema, riassunto, "
        "gancio iniziale e analisi del gancio, formato del video, pubblico, "
        "numeri, e le affermazioni con la citazione testuale che le regge."
    )
)
def leggi_reel(id: str) -> dict:
    parsed = _parse_id(id, atteso="reel")
    if isinstance(parsed, dict):
        return parsed
    return _leggi_reel(parsed[1])


@server.tool(
    description=(
        "Il contenuto completo di UN ARTICOLO di blog, dato il suo id "
        "('blog:45' o solo '45'): testo integrale, fonte, autore, data, "
        "lingua, tema, riassunto, se è in tema, e le affermazioni con la "
        "citazione testuale che le regge."
    )
)
def leggi_articolo(id: str) -> dict:
    parsed = _parse_id(id, atteso="blog")
    if isinstance(parsed, dict):
        return parsed
    return _leggi_articolo(parsed[1])


@server.tool(
    description=(
        "Il contenuto completo di un elemento di QUALSIASI tipo, dato l'id "
        "con il suo prefisso ('reel:123' o 'blog:45'). Comodo dopo "
        "`cerca_tutto`; se sai già il tipo, `leggi_reel` e `leggi_articolo` "
        "dicono più chiaramente cosa stai leggendo."
    )
)
def leggi(id: str) -> dict:
    parsed = _parse_id(id)
    if isinstance(parsed, dict):
        return parsed
    kind, pk = parsed
    if kind == "reel":
        return _leggi_reel(pk)
    if kind == "blog":
        return _leggi_articolo(pk)
    return {"errore": "tipo sconosciuto: usa 'reel:123' o 'blog:45'"}


@server.tool(
    description=(
        "Cerca SOLO nel materiale di riferimento che il cliente ha aggiunto "
        "apposta come ispirazione: puntate TV, interventi, video esterni. "
        "Ogni risultato porta il LINK alla fonte, che è il motivo per cui "
        "questo materiale è in piattaforma — serve a citarlo e a riguardarlo. "
        "Attenzione: alcuni di questi hanno solo titolo e link, senza "
        "trascrizione (vedi `leggi_articolo`), quindi non attribuire loro "
        "affermazioni che non puoi leggere."
    )
)
def cerca_riferimenti(query: str, scope: str = "all", limite: int = 8) -> list[dict]:
    return _search(query, scope, limite, only=None, only_inspiration=True)


@server.tool(
    description=(
        "I blog monitorati, uno per riga: di chi è (Medyca o competitor), "
        "l'indirizzo, quanti articoli ne abbiamo, quando è stato letto "
        "l'ultima volta e se sta dando problemi. Serve a sapere su quali "
        "fonti scritte poggia una risposta — e quali NON sono coperte, che è "
        "l'informazione che evita di spacciare un silenzio per un'assenza."
    )
)
def fonti_blog(scope: str = "all") -> list[dict]:
    from django.db.models import Count, Q

    from core.models import BlogSource

    qs = BlogSource.objects.annotate(
        n=Count("documents", filter=Q(documents__is_active=True)))
    if scope in ("medyca", "owned"):
        qs = qs.filter(owner_type="owned")
    elif scope == "competitor":
        qs = qs.filter(owner_type="competitor")
    return [
        {
            "nome": b.name,
            "di": "Medyca" if b.owner_type == "owned" else "competitor",
            "url": b.index_url,
            "articoli": b.n,
            "attiva": b.is_active,
            "ultima_lettura": (b.last_crawled_at.isoformat()
                               if b.last_crawled_at else None),
            "problema": b.last_error or "",
        }
        for b in qs.order_by("-n")
    ]


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
        parts = path.split("/", 2)
        seg = parts[1] if len(parts) > 1 else ""

        # The invite page: a SHORT link that survives messengers, serving
        # the real connector URL with a copy button. Born of two real
        # incidents in two days: a space gained mid-secret in one paste, the
        # last three secret characters plus /mcp lost in the next forward.
        # Humans copy from a browser reliably; from a wrapped chat message,
        # demonstrably not.
        if seg == "invito" and MCP_INVITE:
            given = _clean(parts[2] if len(parts) > 2 else "")
            if given == MCP_INVITE and scope.get("method") == "GET":
                return await _invite_page(send)
            await _deny(send, 404, "not found")
            return

        # The secret is compared with whitespace and invisible characters
        # removed — a token_urlsafe secret can never contain them, so this
        # only forgives copy-paste damage (measured: "v%20FZ5", zero-width
        # junk from messengers) and accepts nothing an attacker could not
        # already send. A missing /mcp suffix is likewise forgiven: the
        # only endpoint behind the secret IS /mcp.
        if _clean(seg) == MCP_SECRET:
            rest = "/" + parts[2] if len(parts) > 2 and parts[2] else "/mcp"
            if rest == "/":
                rest = "/mcp"
            scope = dict(scope)
            scope["path"] = rest
            return await inner(scope, receive, send)
        await _deny(send, 404, "not found")

    return app


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00a0"))


def _clean(segment: str) -> str:
    """A path segment with whitespace and invisible unicode removed."""
    return "".join(segment.translate(_INVISIBLE).split())


async def _invite_page(send):
    url = f"https://messtudent.com/medyca-mcp/{MCP_SECRET}/mcp"
    html = f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Medyca Content Intelligence — collegamento</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#eef5fd;color:#2c4984;
      display:grid;place-items:center;min-height:100vh;margin:0;padding:24px}}
 .card{{background:#fff;border:1px solid #d5e3f2;border-radius:16px;
       padding:28px;max-width:560px;box-shadow:0 8px 30px rgba(44,73,132,.12)}}
 h1{{font-size:20px;color:#346faa;margin:0 0 6px}}
 p{{font-size:14px;line-height:1.5;margin:10px 0}}
 code{{display:block;background:#eef5fd;border:1px solid #d5e3f2;
      border-radius:10px;padding:12px;font-size:12px;word-break:break-all;
      user-select:all;margin:14px 0}}
 button{{background:#c93b42;color:#fff;border:0;border-radius:999px;
        padding:12px 22px;font-size:15px;font-weight:700;cursor:pointer}}
 button:focus-visible{{outline:2px solid #346faa;outline-offset:2px}}
 .ok{{color:#2e7d32;font-weight:700;display:none}}
 ol{{font-size:14px;line-height:1.7;padding-left:20px}}
</style></head><body><div class="card">
<h1>Medyca Content Intelligence</h1>
<p>Questo è l'indirizzo del connettore per il tuo Claude. È una chiave
d'accesso: <strong>non inoltrarlo</strong>.</p>
<code id="u">{url}</code>
<button onclick="navigator.clipboard.writeText(document.getElementById('u').textContent.trim()).then(()=>{{document.getElementById('ok').style.display='inline'}})">
Copia l'indirizzo</button> <span class="ok" id="ok">✓ copiato</span>
<ol>
<li>Su claude.ai: <strong>Settings → Connectors → Add custom connector</strong></li>
<li>Nome: <strong>Medyca Content Intelligence</strong></li>
<li>Incolla l'indirizzo copiato qui sopra → <strong>Add</strong></li>
</ol>
<p>Nessun login richiesto: l'indirizzo stesso è la chiave.</p>
</div></body></html>"""
    body = html.encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/html; charset=utf-8"),
                            (b"cache-control", b"no-store"),
                            (b"x-robots-tag", b"noindex, nofollow")]})
    await send({"type": "http.response.body", "body": body})


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
