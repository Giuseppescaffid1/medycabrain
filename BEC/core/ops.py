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

import json
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
    "blogscrape": "Scoperta articoli blog",
    "knowledge": "Analisi degli articoli",
    "cluster": "Raggruppamento per tema",
}

_CRON_HUMAN = {
    "0": "mezzanotte", "3": "le 3", "4": "le 4", "8": "le 8",
    "14": "le 14", "16": "le 16",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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



_START = re.compile(r"\[(?P<ts>[\d\-]+ [\d:]+) UTC\] ▶ agent: (?P<stage>\w+)")


def run_history(limit_runs: int = 6, limit_lines: int = 12000) -> list[dict]:
    """Recent pipeline executions, each with its stages and their durations.

    Read from the log the agents write, so the timeline reflects what the
    machine did rather than what anyone thinks it does. Stages are paired by
    their start and completion lines; a stage that started and never finished
    is reported as running rather than dropped — that is exactly the case
    worth seeing.
    """
    path = Path(settings.BASE_DIR) / "logs" / "pipeline.log"
    if not path.exists():
        return []
    try:
        lines = path.read_text(errors="ignore").splitlines()[-limit_lines:]
    except OSError:
        return []

    runs: list[dict] = []
    current: dict | None = None
    pending: dict[str, str] = {}
    order = list(STAGE_LABELS)
    last_pos = len(order)  # forces the first start to open a run

    def _ts(raw: str) -> datetime | None:
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    for line in lines:
        m = _START.search(line)
        if m:
            started = _ts(m.group("ts"))
            if not started:
                continue
            stage = m.group("stage")
            # A new run begins when the pipeline steps backwards. It walks its
            # stages once, in order, so a start that is not past the previous
            # start can only be the next execution — including a partial run
            # like `--only embed`, which begins mid-order.
            #
            # Boundaries cannot be read from the completion lines instead: a
            # stage is only recorded when it finishes, so the first stage of a
            # run finishes after the run has already begun and would be filed
            # under its predecessor.
            pos = order.index(stage) if stage in order else len(order)
            if current is None or pos <= last_pos:
                current = {"started": started.isoformat(), "stages": []}
                runs.append(current)
            last_pos = pos
            pending[stage] = started.isoformat()
            continue

        m = _LOG_LINE.search(line)
        if not m or current is None:
            continue
        stage = m.group("stage")
        finished = _ts(m.group("ts"))
        if not finished:
            continue
        current["stages"].append({
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage),
            "started": pending.pop(stage, None),
            "finished": finished.isoformat(),
            "seconds": round(float(m.group("secs"))),
            "result": m.group("payload")[:160],
        })
        current["finished"] = finished.isoformat()

    # Whatever started and never wrote a completion line is still going. It has
    # to be shown: a stage like the transcription runs for the best part of an
    # hour, and while it does, a timeline built only from completions is frozen
    # — which reads as "nothing is happening" at the exact moment most is.
    if current is not None:
        run_started = current["started"]
        for stage, started in pending.items():
            if started < run_started:
                continue  # left over from an earlier run that died mid-stage
            begun = _ts(started.replace("T", " ")[:19])
            elapsed = round((_now() - begun).total_seconds()) if begun else 0
            current["stages"].append({
                "stage": stage,
                "label": STAGE_LABELS.get(stage, stage),
                "started": started,
                "finished": None,
                "seconds": max(elapsed, 0),
                "result": "",
                "running": True,
            })
            current["running"] = True

    for r in runs:
        r["seconds"] = sum(s["seconds"] for s in r["stages"])
    # newest first, and only runs that actually did something
    return [r for r in reversed(runs) if r["stages"]][:limit_runs]


# The commands this project runs itself. Nothing outside this map is ever
# reported, so a stray process on the machine cannot appear in the client's
# page as if it were part of the pipeline.
JOBS = {
    "run_pipeline": ("Pipeline completa", "pipeline.log"),
    "reprocess": ("Rianalisi dei contenuti", "reprocess.log"),
    "ingest_blog": ("Import del blog", "blog.log"),
}

# The lines worth showing: what an agent reports about a single item. Only
# INFO — a warning carries a Python repr in English, which on a page the
# client reads is alarming noise rather than progress. Failures belong in the
# log, not in the answer to "what is it doing right now".
_ACTIVITY = re.compile(r"INFO\s+(?:pipeline|core)\.[\w.]+\s+(?P<msg>.+)")


def _last_activity_line(log: str, tail: int = 400) -> str:
    path = Path(settings.BASE_DIR) / "logs" / log
    if not path.exists():
        return ""
    try:
        with path.open(errors="ignore") as fh:
            lines = fh.readlines()[-tail:]
    except OSError:
        return ""
    for line in reversed(lines):
        m = _ACTIVITY.search(line)
        if m:
            return m.group("msg").strip()[:180]
    return ""


def _running_stage(history: list[dict]) -> str:
    """The stage the pipeline is inside right now, or "" if between stages."""
    for run in history[:1]:
        for s in run["stages"]:
            if s.get("running"):
                return s["label"]
    return ""


def activity(history: list[dict] | None = None) -> list[dict]:
    """The project's own commands executing right now, with what they just did.

    Read from the process table rather than from a job record: a command
    started by hand or by cron leaves no row in the database, and those are
    exactly the long runs someone watches this page to follow.
    """
    out = []
    history = run_history(limit_runs=1) if history is None else history
    raw = _run(["ps", "-eo", "pid,etimes,args", "--no-headers"], timeout=6)
    for line in raw.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, args = parts
        # The real process, not the shell that spawned it: a wrapper's command
        # line quotes the same words and would double every entry.
        if not Path(args.split()[0]).name.startswith("python"):
            continue
        if "manage.py" not in args:
            continue
        tokens = args.split()
        try:
            cmd = tokens[tokens.index("manage.py") + 1]
        except (ValueError, IndexError):
            continue
        if cmd not in JOBS:
            continue
        label, log = JOBS[cmd]
        out.append({
            "job": cmd,
            "label": label,
            "pid": int(pid) if pid.isdigit() else 0,
            "seconds": int(etimes) if etimes.isdigit() else 0,
            "stage": _running_stage(history) if cmd == "run_pipeline" else "",
            "detail": _last_activity_line(log),
        })
    return sorted(out, key=lambda j: -j["seconds"])


def reanalysis() -> dict | None:
    """How far the switch to the current analysis model has got.

    The stage counters cannot show this: these reels were already analysed, so
    "analizzati" does not move while every one of them is being redone. What
    moves is which model produced the analysis.
    """
    from core import models as m
    from llm import client

    target = (client.model_for("analysis") or "").split("/")[-1]
    if not target:
        return None
    qs = m.Enrichment.objects.exclude(evidence="insufficient")
    total = qs.count()
    if not total:
        return None
    done = qs.filter(llm_model__icontains=target).count()
    return {
        "model": target,
        "done": done,
        "total": total,
        "pct": round(done * 100 / total),
    }


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


def evals(limit: int = 12) -> list[dict]:
    """The evaluation runs, newest first, straight from logs/evals/.

    The suite (manage.py eval_mcp) is the source of truth; this just reads
    what it wrote, so the page can never disagree with the scorecard files.
    """
    evdir = Path(settings.BASE_DIR) / "logs" / "evals"
    if not evdir.exists():
        return []
    out = []
    for f in sorted(evdir.glob("eval-*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        cases = data.get("cases", {})
        out.append({
            "at": data.get("at"),
            "metrics": data.get("metrics", {}),
            "latency_ms": data.get("latency_ms", {}),
            "cases": [{"name": k, "pass": bool(v.get("pass")),
                       "detail": v.get("detail", "")}
                      for k, v in cases.items()],
            "passed": sum(1 for v in cases.values() if v.get("pass")),
            "total": len(cases),
        })
    return out


def snapshot() -> dict:
    # Read once and share: this endpoint is polled every five seconds per open
    # tab, and each call would otherwise re-read the whole pipeline log.
    history = run_history()
    return {
        "services": services(),
        "schedules": schedules(),
        "last_runs": last_runs(),
        "history": history,
        "activity": activity(history),
        "evals": evals(),
        "reanalysis": reanalysis(),
        "now": _now().isoformat(),
        "models": models(),
        "provider": settings.FAST_LLM_BASE_URL,
    }
