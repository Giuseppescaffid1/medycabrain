#!/usr/bin/env python3
"""
tools/plane_tickets.py
======================
Pull the medycabrain project tickets from the self-hosted Plane instance
(pm.messtudent.com) via its REST API and print them, or write a Markdown
snapshot to TICKETS.md.

Config comes from environment variables (or a repo-root `.plane.env` file,
gitignored):

    PLANE_BASE_URL   default https://pm.messtudent.com
    PLANE_API_TOKEN  a Plane personal API token  (required)
    PLANE_WORKSPACE  default medyca
    PLANE_PROJECT    default 9f96ea3a-4a27-496f-9e3a-233d0a26475a

Usage:
    python tools/plane_tickets.py            # print tickets
    python tools/plane_tickets.py --markdown # write TICKETS.md
    python tools/plane_tickets.py --json     # dump raw JSON

Only depends on the Python standard library.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env = REPO_ROOT / ".plane.env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _cfg():
    _load_dotenv()
    token = os.environ.get("PLANE_API_TOKEN")
    if not token:
        sys.exit("PLANE_API_TOKEN not set (env or .plane.env). See tools/plane_tickets.py.")
    return {
        "base": os.environ.get("PLANE_BASE_URL", "https://pm.messtudent.com").rstrip("/"),
        "token": token,
        "workspace": os.environ.get("PLANE_WORKSPACE", "medyca"),
        "project": os.environ.get("PLANE_PROJECT", "9f96ea3a-4a27-496f-9e3a-233d0a26475a"),
    }


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"X-API-Key": token, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _paginate(base_url: str, token: str) -> list[dict]:
    """Follow Plane's cursor pagination and return all results."""
    items, url = [], base_url
    seen_cursors = set()
    while url:
        data = _get(url, token)
        if isinstance(data, list):
            return data
        items.extend(data.get("results", []))
        nxt = data.get("next_page_results") and data.get("next_cursor")
        if not nxt or nxt in seen_cursors:
            break
        seen_cursors.add(nxt)
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}cursor={nxt}"
    return items


def fetch(cfg: dict) -> tuple[list[dict], dict]:
    api = f"{cfg['base']}/api/v1/workspaces/{cfg['workspace']}/projects/{cfg['project']}"
    issues = _paginate(f"{api}/issues/?per_page=100", cfg["token"])
    # state id -> name map
    states = {}
    try:
        for s in _paginate(f"{api}/states/?per_page=100", cfg["token"]):
            states[s["id"]] = s["name"]
    except Exception:  # noqa: BLE001 — states are a nicety, not required
        pass
    return issues, states


PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4, None: 4}


def _rows(cfg, issues, states):
    ident = "MEDYC"
    rows = []
    for i in issues:
        rows.append({
            "ref": f"{ident}-{i.get('sequence_id')}",
            "seq": i.get("sequence_id") or 0,
            "name": (i.get("name") or "").strip(),
            "state": states.get(i.get("state"), ""),
            "priority": i.get("priority") or "none",
            "description": (i.get("description_stripped") or "").strip(),
            "url": f"{cfg['base']}/{cfg['workspace']}/projects/{cfg['project']}/issues/{i.get('id')}/",
        })
    rows.sort(key=lambda r: (PRIORITY_ORDER.get(r["priority"], 4), -r["seq"]))
    return rows


def print_tickets(cfg, rows):
    print(f"\nMedyca — {len(rows)} tickets ({cfg['workspace']})\n")
    for r in rows:
        print(f"  {r['ref']}  [{r['priority']:<6}] {r['state']:<8}  {r['name']}")
        if r["description"]:
            print(f"      {r['description'][:100]}")


def write_markdown(cfg, rows):
    lines = ["# Medyca — Tickets", "",
             f"Snapshot from Plane (`{cfg['workspace']}`). "
             "Regenerate with `python tools/plane_tickets.py --markdown`.", "",
             "| Ref | Priorità | Stato | Titolo |", "|---|---|---|---|"]
    for r in rows:
        name = r["name"].replace("|", "\\|")
        lines.append(f"| [{r['ref']}]({r['url']}) | {r['priority']} | {r['state']} | {name} |")
    lines.append("")
    for r in rows:
        if r["description"]:
            lines += [f"### {r['ref']} — {r['name']}", "", r["description"], ""]
    out = REPO_ROOT / "TICKETS.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out} ({len(rows)} tickets)")


def main():
    cfg = _cfg()
    issues, states = fetch(cfg)
    rows = _rows(cfg, issues, states)
    if "--json" in sys.argv:
        print(json.dumps(issues, indent=2, ensure_ascii=False))
    elif "--markdown" in sys.argv:
        write_markdown(cfg, rows)
    else:
        print_tickets(cfg, rows)


if __name__ == "__main__":
    main()
