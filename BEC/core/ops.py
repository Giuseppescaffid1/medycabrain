"""
core/ops.py
===========
What is actually running, read from the machine rather than described.

A documentation page that lists schedules from memory drifts the moment
anything changes, and then reassures the reader about a job that no longer
exists. Everything here is read live: the crontab as installed, systemd's own
view of each service, and the last completion of each pipeline stage taken
from the log the agents write.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Only these units are ever queried: a fixed list, so nothing a request says
# can reach systemctl.
SERVICES = [
    ("medycabrain-backend", "API e interfaccia"),
    ("nginx", "Server web"),
    ("postgresql", "Database"),
    ("ollama", "Modello locale di riserva"),
]

STAGE_LABELS = {
    "scrape": "Raccolta da Instagram",
    "download": "Download dei video",
    "transcribe": "Trascrizione audio",
    "enrich": "Analisi dei contenuti",
    "embed": "Indicizzazione per la ricerca",
    "knowledge": "Import del blog",
    "cluster": "Raggruppamento per tema",
}

_CRON_HUMAN = {
    "0": "mezzanotte", "3": "le 3", "4": "le 4", "8": "le 8",
    "14": "le 14", "16": "le 16",
}


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception as exc:  # noqa: BLE001 — never let ops reporting break a page
        logger.warning("[ops] %s: %r", " ".join(cmd), exc)
        return ""


def services() -> list[dict]:
    return [
        {"unit": unit, "label": label, "state": _run(["systemctl", "is-active", unit]) or "unknown"}
        for unit, label in SERVICES
    ]


def _describe(minute: str, hour: str, dow: str) -> str:
    """A cron line in words. Only the shapes this project uses."""
    hours = [h for h in hour.split(",") if h.isdigit()]
    when = ", ".join(f"{int(h):02d}:{int(minute):02d}" for h in hours) if hours else f"{hour} {minute}"
    if dow != "*":
        days = {"1": "lunedì", "2": "martedì", "3": "mercoledì", "4": "giovedì",
                "5": "venerdì", "6": "sabato", "0": "domenica"}
        return f"ogni {days.get(dow, dow)} alle {when}"
    return f"ogni giorno alle {when}"


def schedules() -> list[dict]:
    """The crontab as installed, not as remembered."""
    out = []
    raw = _run(["crontab", "-l"], timeout=8)
    comment = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#"):
            comment = line.lstrip("# ").strip()
            continue
        if not line or "medycabrain" not in line:
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        minute, hour, _dom, _mon, dow, cmd = parts
        stage = "pipeline completa"
        if "--only" in cmd:
            stage = cmd.split("--only", 1)[1].split()[0]
        elif "--skip-cluster" in cmd:
            stage = "pipeline senza clustering"
        elif "ingest_blog" in cmd:
            stage = "blog"
        out.append({
            "what": comment or stage,
            "stage": stage,
            "when": _describe(minute, hour, dow),
            "niced": cmd.strip().startswith("nice") or " nice " in cmd,
        })
        comment = ""
    return out


_LOG_LINE = re.compile(
    r"\[(?P<ts>[\d\-]+ [\d:]+) UTC\] ✓ (?P<stage>\w+) done in (?P<secs>[\d.]+)s — (?P<payload>.*)"
)


def last_runs(limit_lines: int = 4000) -> list[dict]:
    """Last completion of each pipeline stage, from the log the agents write."""
    path = Path(settings.BASE_DIR) / "logs" / "pipeline.log"
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="ignore").splitlines()[-limit_lines:]
    except OSError:
        return []
    seen: dict[str, dict] = {}
    for line in lines:
        m = _LOG_LINE.search(line)
        if not m:
            continue
        stage = m.group("stage")
        try:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        seen[stage] = {
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage),
            "at": ts.isoformat(),
            "seconds": round(float(m.group("secs"))),
            "result": m.group("payload")[:160],
        }
    order = list(STAGE_LABELS)
    return sorted(seen.values(), key=lambda r: order.index(r["stage"]) if r["stage"] in order else 99)


def models() -> list[dict]:
    """Which model serves which kind of work, read from the live settings."""
    from llm import client

    return [
        {"task": "Trascrizione audio", "model": settings.FAST_STT_MODEL,
         "why": "riconosce la terminologia medica grazie a un glossario"},
        {"task": "Analisi dei contenuti", "model": client.model_for("analysis"),
         "why": "legge la trascrizione ed estrae tema, gancio e affermazioni"},
        {"task": "Raggruppamento e piano editoriale", "model": client.model_for("reasoning"),
         "why": "decide come sono organizzati i temi e cosa proporre"},
        {"task": "Estrazione di massa", "model": client.model_for("bulk"),
         "why": "centinaia di chiamate meccaniche"},
        {"task": "Ricerca per significato", "model": settings.EMBEDDINGS_MODEL.split("/")[-1],
         "why": "trasforma i testi in vettori per la ricerca semantica"},
    ]


def snapshot() -> dict:
    return {
        "services": services(),
        "schedules": schedules(),
        "last_runs": last_runs(),
        "models": models(),
        "provider": settings.FAST_LLM_BASE_URL,
    }
