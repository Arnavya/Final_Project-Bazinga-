"""Readiness check: can this process answer questions right now?

Streamlit's own `/_stcore/health` only proves the web server is up. This check proves the app
has what it needs to answer: the ingest-built stores exist and parse, the scenarios file is
there, and the state directory is writable (the learning loop writes to it).

Stdlib only, so it is cheap to run as a container HEALTHCHECK or Kubernetes exec probe:

    python -m engine.health            # prints JSON, exit 0 = ready, 1 = not ready
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from engine import config


def _check_json(path: Path) -> str | None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"{path.name}: unreadable ({type(exc).__name__})"
    return None


def check() -> Dict[str, Any]:
    """Return {ready, version, git_sha, stores_dir, problems[]}."""
    problems: List[str] = []

    for path in config.REQUIRED_STORE_FILES:
        if not path.is_file():
            problems.append(f"{path.name}: missing")
        elif path.suffix == ".json":
            err = _check_json(path)
            if err:
                problems.append(err)
        elif path.suffix == ".npz" and not zipfile.is_zipfile(path):
            problems.append(f"{path.name}: not a valid .npz archive")

    if not config.SCENARIOS_FILE.is_file():
        problems.append("scenarios.json: missing")

    if config.STORES_DIR.is_dir():
        try:
            fd, probe = tempfile.mkstemp(prefix=".health-", dir=config.STORES_DIR)
            os.close(fd)
            os.unlink(probe)
        except OSError as exc:
            problems.append(f"stores dir not writable ({type(exc).__name__})")
    else:
        problems.append("stores dir: missing")

    return {
        "ready": not problems,
        "version": config.APP_VERSION,
        "git_sha": config.GIT_SHA,
        "llm_provider": "stub" if config.USE_STUB else config.LLM_PROVIDER,
        "stores_dir": str(config.STORES_DIR),
        "problems": problems,
    }


def main() -> int:
    result = check()
    print(json.dumps(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
