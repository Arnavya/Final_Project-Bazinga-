"""Persist reasoning history so improvement can be evaluated over time.

Transparent JSON files (easy for the dashboard to read and for graders to
inspect). `history.json` holds the latest benchmark run; `ask_log.json` holds
live "Ask" events appended over time.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from engine import config


def save_benchmark(results: List[Dict[str, Any]]) -> None:
    config.ensure_dirs()
    (config.STORES_DIR / "history.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")


def load_benchmark() -> List[Dict[str, Any]]:
    path = config.STORES_DIR / "history.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def append_ask(event: Dict[str, Any]) -> None:
    config.ensure_dirs()
    path = config.STORES_DIR / "ask_log.json"
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    log.append(event)
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def load_ask_log() -> List[Dict[str, Any]]:
    path = config.STORES_DIR / "ask_log.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
