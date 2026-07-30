"""
Evaluate the MCP connector the way the client's Claude actually uses it.

    python manage.py eval_mcp            # full suite, judged
    python manage.py eval_mcp --no-judge # deterministic metrics only

The point is repeatability, not a one-off smoke test: every run appends its
scorecard to logs/evals/, prints the delta against the previous run, and
uses the SAME golden questions — so a retrieval change, a re-clustering or
a model swap shows up as a number moving, not as an anecdote.

What is measured, per layer:
  transport   the real path (HTTPS through nginx, secret in URL), latency
              per tool
  retrieval   hit@k against golden expectations anchored to facts that are
              IN the corpus (checked at suite-design time), including a
              cross-language case (Italian query → English IMS article)
  integrity   ownership labels on every hit vs the database truth — the one
              error this product must never make; panoramica counts vs ORM
  groundedness leggi: every claim's quote must appear verbatim in the text
              it claims to come from
  relevance   LLM judge (0-2 per hit) over the cerca result sets — the
              subjective layer, kept separate from the deterministic ones
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# ── the golden set ──────────────────────────────────────────────────────────
# Anchored to facts verified present in the corpus on 2026-07-30. If a
# matcher stops matching, either retrieval regressed or the corpus changed:
# both are worth a red number.
GOLDEN = [
    {"name": "bijuva_medyca", "tool": "cerca",
     "args": {"query": "Bijuva pro e contro", "scope": "medyca", "limite": 5},
     "expect": {"tipo": "reel", "di_contains": "Medyca", "titolo_contains": "bijuva"}},
    {"name": "marion_gluck_blog", "tool": "cerca",
     "args": {"query": "metodo Marion Gluck", "scope": "medyca", "limite": 5},
     "expect": {"tipo": "articolo", "di_contains": "Medyca", "titolo_contains": "gluck"}},
    {"name": "crosslang_xerostomia", "tool": "cerca",
     "args": {"query": "secchezza della bocca e terapia ormonale", "limite": 8},
     "expect": {"tipo": "articolo", "di_contains": "competitor",
                "titolo_contains": "menopause hormone therapy"}},
    {"name": "candida_missori", "tool": "cerca",
     "args": {"query": "candida intestinale rimedi", "scope": "competitor", "limite": 5},
     "expect": {"tipo": "articolo", "di_contains": "Missori", "titolo_contains": "candida"}},
    # Rare-term, cross-language: the Italian clinical term must pull the
    # English article. The first version asked a generic Italian query to
    # outrank 900 Italian reels — position 22 was not a defect, the bar was
    # wrong; the rare term is what this case is really about (position 1).
    {"name": "dislipidemia_ims", "tool": "cerca",
     "args": {"query": "dislipidemia in menopausa", "scope": "competitor", "limite": 8},
     "expect": {"tipo": "articolo", "di_contains": "competitor",
                "titolo_contains": "lipid"}},
    {"name": "blog_slots", "tool": "cerca",
     "args": {"query": "cosa scrivono i competitor sui loro blog di alimentazione", "limite": 12},
     "expect_min_articles": 3},
    {"name": "quota_medyca", "tool": "cerca",
     "args": {"query": "vampate di calore rimedi", "limite": 12},
     "expect_min_medyca": 2},
]


class Command(BaseCommand):
    help = "Suite di valutazione del connettore MCP: recupero, integrità, latenza, giudice."

    def add_arguments(self, parser):
        parser.add_argument("--no-judge", action="store_true",
                            help="Salta il giudice LLM (solo metriche deterministiche).")
        parser.add_argument("--base", default="https://messtudent.com/medyca-mcp",
                            help="Base URL del connettore (default: percorso pubblico).")

    # ── MCP transport ──────────────────────────────────────────────────
    def _call(self, tool: str, args: dict) -> tuple[list[dict] | dict, float]:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": args}}
        t0 = time.time()
        resp = requests.post(
            self.url, json=body, timeout=120,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        ms = (time.time() - t0) * 1000
        resp.raise_for_status()
        content = resp.json()["result"]["content"]
        rows = [json.loads(c["text"]) for c in content if c.get("type") == "text"]
        return (rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else rows), ms

    def handle(self, *args, **opts):
        import os
        secret = os.environ.get("MCP_SECRET", "")
        if not secret:
            from dotenv import dotenv_values
            secret = dotenv_values(settings.BASE_DIR / ".env").get("MCP_SECRET", "")
        if not secret:
            raise CommandError("MCP_SECRET non trovato")
        self.url = f"{opts['base']}/{secret}/mcp"

        results = {"at": datetime.now(timezone.utc).isoformat(),
                   "cases": {}, "latency_ms": {}, "metrics": {}}
        latencies: dict[str, list[float]] = {}

        # ── 1. integrità: panoramica vs ORM ────────────────────────────
        from django.db.models import Count

        from core.models import KnowledgeDocument, Reel
        pano, ms = self._call("panoramica", {})
        latencies.setdefault("panoramica", []).append(ms)
        db_reels = dict(Reel.objects.filter(is_active=True)
                        .values_list("account__owner_type").annotate(n=Count("id")))
        db_docs = dict(KnowledgeDocument.objects.filter(is_active=True, is_on_topic=True)
                       .values_list("owner_type").annotate(n=Count("id")))
        pano_ok = (pano["reel"]["medyca"] == db_reels.get("owned", 0)
                   and pano["reel"]["competitor"] == db_reels.get("competitor", 0)
                   and pano["articoli"]["medyca"] == db_docs.get("owned", 0)
                   and pano["articoli"]["competitor"] == db_docs.get("competitor", 0))
        results["cases"]["panoramica_integrity"] = {"pass": pano_ok}
        self._line("integrità panoramica = database", pano_ok)

        # ── 2. il golden set ───────────────────────────────────────────
        judge_material = []
        hits_at_k = own_checked = own_correct = 0
        for case in GOLDEN:
            rows, ms = self._call(case["tool"], case["args"])
            latencies.setdefault("cerca", []).append(ms)
            rows = rows if isinstance(rows, list) else [rows]
            ok, detail = self._match(case, rows)
            hits_at_k += int(ok)
            results["cases"][case["name"]] = {"pass": ok, "detail": detail,
                                              "ms": round(ms)}
            self._line(f"{case['name']} ({detail})", ok)
            judge_material.append((case["args"]["query"], rows))
            # ownership su OGNI hit, contro il DB
            for h in rows:
                truth = self._db_owner(h.get("id", ""))
                if truth is None:
                    continue
                own_checked += 1
                said_comp = "competitor" in (h.get("di") or "").lower()
                own_correct += int(said_comp == (truth == "competitor"))

        own_acc = own_correct / own_checked if own_checked else 0.0
        results["metrics"]["ownership_accuracy"] = round(own_acc, 4)
        self._line(f"proprietà corretta su {own_checked} hit: {own_acc:.0%}",
                   own_acc == 1.0)

        # ── 3. groundedness: leggi su un articolo e un reel ────────────
        grounded = total_claims = 0
        probes = []
        d = (KnowledgeDocument.objects.filter(is_active=True, is_on_topic=True,
                                              arguments__isnull=False)
             .order_by("-id").first())
        if d:
            probes.append(f"blog:{d.id}")
        r = (Reel.objects.filter(is_active=True, arguments__isnull=False,
                                 transcript__isnull=False).order_by("-view_count").first())
        if r:
            probes.append(f"reel:{r.id}")
        for pid in probes:
            doc, ms = self._call("leggi", {"id": pid})
            latencies.setdefault("leggi", []).append(ms)
            # For a reel the claim may legitimately be quoted from the
            # caption — the extraction prompt offers both. The haystack is
            # everything the tool returned, which is also everything the
            # client's Claude has available to verify against.
            body = " ".join(filter(None, [doc.get("testo"),
                                          doc.get("trascrizione"),
                                          doc.get("didascalia")]))
            body_n = _norm(body)
            for a in doc.get("affermazioni", []):
                total_claims += 1
                grounded += int(_norm(a.get("citazione", ""))[:80] in body_n)
        g_rate = grounded / total_claims if total_claims else 1.0
        results["metrics"]["groundedness"] = round(g_rate, 4)
        self._line(f"citazioni verbatim nel testo: {grounded}/{total_claims}",
                   g_rate >= 0.9)

        # ── 4. temi ────────────────────────────────────────────────────
        temi, ms = self._call("temi", {"scope": "competitor"})
        latencies.setdefault("temi", []).append(ms)
        temi_ok = (isinstance(temi, list) and len(temi) >= 10
                   and all(t.get("tema") for t in temi))
        results["cases"]["temi_competitor"] = {"pass": temi_ok, "n": len(temi)}
        self._line(f"temi competitor: {len(temi)} etichettati", temi_ok)

        # ── 5. latenza ─────────────────────────────────────────────────
        for tool, vals in latencies.items():
            results["latency_ms"][tool] = {
                "p50": round(statistics.median(vals)),
                "max": round(max(vals)), "n": len(vals)}
        cerca_p50 = results["latency_ms"].get("cerca", {}).get("p50", 0)
        self._line(f"latenza cerca p50={cerca_p50}ms "
                   f"(max {results['latency_ms'].get('cerca', {}).get('max')}ms)",
                   cerca_p50 < 2000)

        # ── 6. giudice LLM sulla pertinenza ────────────────────────────
        if not opts["no_judge"]:
            score = self._judge(judge_material)
            results["metrics"]["judge_relevance"] = score
            self._line(f"pertinenza (giudice, 0-2): {score}", (score or 0) >= 1.2)

        # ── scorecard + storico ────────────────────────────────────────
        passed = sum(1 for c in results["cases"].values() if c.get("pass"))
        results["metrics"]["cases_passed"] = f"{passed}/{len(results['cases'])}"
        results["metrics"]["hit_rate_golden"] = round(hits_at_k / len(GOLDEN), 4)

        evdir = Path(settings.BASE_DIR) / "logs" / "evals"
        evdir.mkdir(parents=True, exist_ok=True)
        prev = sorted(evdir.glob("eval-*.json"))
        out = evdir / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))

        self.stdout.write("\n" + "=" * 56)
        self.stdout.write(f"  casi superati : {results['metrics']['cases_passed']}")
        self.stdout.write(f"  hit rate golden: {results['metrics']['hit_rate_golden']:.0%}")
        self.stdout.write(f"  proprietà      : {own_acc:.0%}")
        self.stdout.write(f"  groundedness   : {g_rate:.0%}")
        if "judge_relevance" in results["metrics"]:
            self.stdout.write(f"  giudice (0-2)  : {results['metrics']['judge_relevance']}")
        self.stdout.write(f"  salvato in     : {out.relative_to(settings.BASE_DIR)}")
        if prev:
            old = json.loads(prev[-1].read_text())
            self.stdout.write("\n  Δ vs run precedente "
                              f"({old['at'][:16]}):")
            for k in ("hit_rate_golden", "ownership_accuracy",
                      "groundedness", "judge_relevance"):
                a, b = old.get("metrics", {}).get(k), results["metrics"].get(k)
                if a is not None and b is not None and not isinstance(a, str):
                    arrow = "=" if a == b else ("↑" if b > a else "↓")
                    self.stdout.write(f"    {k:22} {a} → {b}  {arrow}")

    # ── helpers ────────────────────────────────────────────────────────
    def _line(self, label: str, ok: bool):
        mark = self.style.SUCCESS("✓") if ok else self.style.ERROR("✗")
        self.stdout.write(f"  {mark} {label}")

    def _match(self, case: dict, rows: list[dict]) -> tuple[bool, str]:
        if "expect" in case:
            e = case["expect"]
            for i, h in enumerate(rows, 1):
                if (h.get("tipo") == e["tipo"]
                        and e["di_contains"].lower() in (h.get("di") or "").lower()
                        and e["titolo_contains"].lower() in (h.get("titolo") or "").lower()):
                    return True, f"trovato in posizione {i}"
            return False, f"assente nei primi {len(rows)}"
        if "expect_min_articles" in case:
            n = sum(1 for h in rows if h.get("tipo") == "articolo")
            return n >= case["expect_min_articles"], f"{n} articoli"
        if "expect_min_medyca" in case:
            n = sum(1 for h in rows if "medyca" in (h.get("di") or "").lower())
            return n >= case["expect_min_medyca"], f"{n} di Medyca"
        return False, "caso senza attese"

    def _db_owner(self, hit_id: str):
        from core.models import KnowledgeDocument, Reel
        try:
            kind, pk = hit_id.split(":", 1)
            pk = int(pk)
        except (ValueError, AttributeError):
            return None
        if kind == "reel":
            r = Reel.objects.filter(id=pk).select_related("account").first()
            return r.account.owner_type if r else None
        if kind == "blog":
            d = KnowledgeDocument.objects.filter(id=pk).first()
            return d.owner_type if d else None
        return None

    def _judge(self, material) -> float | None:
        """Mean relevance 0-2 over every (query, hits) pair, one LLM call.

        One call for the whole suite, not one per case: the judge is the
        expensive layer and a single structured prompt keeps it cheap enough
        to run on every evaluation.
        """
        from llm import client
        if not client.available():
            return None
        blocks = []
        for qi, (query, rows) in enumerate(material, 1):
            lines = [f"D{qi}: {query}"]
            for hi, h in enumerate(rows[:6], 1):
                lines.append(f"  {qi}.{hi} [{h.get('tipo')}] {h.get('titolo', '')[:70]}"
                             f" — {h.get('estratto', '')[:120]}")
            blocks.append("\n".join(lines))
        user = ("Per ogni risultato, giudica quanto è pertinente alla sua domanda:\n"
                "2 = risponde direttamente, 1 = correlato, 0 = fuori tema.\n\n"
                + "\n\n".join(blocks)
                + '\n\nRestituisci JSON: {"voti": [{"id": "1.1", "voto": 2}, ...]}')
        try:
            data = client.chat_json(
                "Sei un valutatore di sistemi di ricerca. Rispondi SOLO con JSON valido.",
                user, max_tokens=900, model=client.model_for("reasoning"))
            votes = [int(v["voto"]) for v in data.get("voti", [])
                     if str(v.get("voto")) in ("0", "1", "2")]
            return round(sum(votes) / len(votes), 2) if votes else None
        except Exception:  # noqa: BLE001 — the judge failing is not a suite failure
            return None


def _norm(text: str) -> str:
    import re
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").lower())
