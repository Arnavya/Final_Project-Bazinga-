"""Turn the synthetic sources into self-contained, metadata-rich chunks.

One chunk per natural unit (a ticket, a commit, a Slack thread, a wiki doc, an
incident, a release). Each chunk gets a short context prefix before embedding
(improves retrieval) and `entity_ids` linking it to graph entities.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from engine import config


def _load(name: str) -> Any:
    return json.loads((config.SOURCES_DIR / name).read_text(encoding="utf-8"))


def build_chunks() -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []

    def add(source_id: str, source_type: str, service: str, entity_ids: List[str], text: str) -> None:
        chunks.append({
            "chunk_id": source_id,
            "source_id": source_id,
            "source_type": source_type,
            "service": service,
            "entity_ids": sorted({e for e in entity_ids if e}),
            "text": text.strip(),
        })

    for t in _load("tickets.json"):
        ents = [t["service"], t["owner"], t["id"], *t.get("blocks", []), *t.get("relates", [])]
        text = (f"[Ticket {t['id']}] {t['title']} "
                f"(status={t['status']}, service={t['service']}, owner={t['owner']}). {t['body']}")
        add(t["id"], "ticket", t["service"], ents, text)

    for c in _load("commits.json"):
        ents = [c["service"], c["id"]] + ([c["release"]] if c.get("release") else [])
        rel = c.get("release") or "none"
        text = f"[Commit {c['id']}] service={c['service']} release={rel}: {c['message']}"
        add(c["id"], "commit", c["service"], ents, text)

    for s in _load("slack.json"):
        ents = list(s.get("entities", [])) + [s["id"]]
        text = f"[Slack {s['channel']} {s['id']}] {s['text']}"
        add(s["id"], "slack", "", ents, text)

    for i in _load("incidents.json"):
        ents = [i["service"], i["id"]]
        text = f"[Incident {i['id']}] {i['title']} (service={i['service']}). {i['summary']}"
        add(i["id"], "incident", i["service"], ents, text)

    for r in _load("releases.json"):
        text = f"[Release {r['id']}] {r['name']} (status={r['status']}). {r['note']}"
        add(r["id"], "release", "", [r["id"]], text)

    for w in _load("wiki_index.json"):
        body = (config.SOURCES_DIR / w["file"].replace("wiki/", "wiki/")).read_text(encoding="utf-8")
        text = f"[Wiki {w['id']}] {w['title']}. {body}"
        add(w["id"], "wiki", w.get("service", ""), [w["id"], w.get("service", "")], text)

    return chunks
