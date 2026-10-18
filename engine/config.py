"""Central configuration: paths, LLM/embedding settings, retrieval params.

All paths are derived from this file's location with pathlib, so the project
runs identically on Linux and macOS with no hardcoded absolute paths.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent          # project root
DATA_DIR = BASE_DIR / "data"
SOURCES_DIR = DATA_DIR / "sources"
SCENARIOS_FILE = DATA_DIR / "scenarios.json"


# --- Minimal .env loader (avoids a python-dotenv dependency) ---
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)  # don't override the real environment


_load_dotenv(BASE_DIR / ".env")


# STORES_DIR can be pointed at a separate writable volume (container / Kubernetes);
# default keeps the original location next to the code.
STORES_DIR = Path(os.environ.get("STORES_DIR", str(BASE_DIR / "stores"))).resolve()
VECTOR_STORE_FILE = STORES_DIR / "vector_store.npz"
VECTOR_META_FILE = STORES_DIR / "vector_meta.json"
GRAPH_FILE = STORES_DIR / "graph.json"
LESSONS_FILE = STORES_DIR / "lessons.json"
KG_OVERRIDES_FILE = STORES_DIR / "kg_overrides.json"
ANSWERS_FILE = STORES_DIR / "question_answers.json"   # exact-question expert answers

# Files the app cannot answer without (built by the ingest step).
REQUIRED_STORE_FILES = (VECTOR_STORE_FILE, VECTOR_META_FILE, GRAPH_FILE)


# --- Release identification ---
# Set at image build time (Dockerfile build args) or by the deployment; "dev" locally.
APP_VERSION = os.environ.get("APP_VERSION", "dev").strip() or "dev"
GIT_SHA = os.environ.get("GIT_SHA", "unknown").strip() or "unknown"


# --- Logging ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").strip().lower()   # text | json


# --- LLM settings ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_SMALL_MODEL = os.environ.get("LLM_SMALL_MODEL", "llama-3.1-8b-instant")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.1"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))

# No real model configured -> every LLM-backed stage falls back to a deterministic
# heuristic so the full pipeline still runs end-to-end offline.
USE_STUB = LLM_PROVIDER == "stub" or (LLM_PROVIDER == "groq" and not GROQ_API_KEY)


# --- Embedding / reranking ---
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-base")
HASHING_DIM = 512  # dimensionality of the dependency-free fallback embedder


# --- Retrieval parameters (tunable accuracy levers) ---
TOP_K_DENSE = 20          # candidates from vector search
TOP_K_BM25 = 20           # candidates from keyword search
RRF_K = 60                # Reciprocal Rank Fusion constant
RERANK_INPUT = 20         # how many fused candidates to rerank
FINAL_K = 6               # evidence chunks passed to the LLM
LESSON_TOP_K = 3          # lessons retrieved per question
LESSON_SIM_THRESHOLD = 0.30    # min similarity to inject a lesson
LESSON_DEDUP_THRESHOLD = 0.85  # above this, reinforce an existing lesson instead of adding
CONFIDENCE_THRESHOLD = 0.25    # below this top score -> "insufficient evidence"


# --- Success-criteria targets (from the project brief) ---
TARGETS = {
    "similarity": 0.75,
    "root_cause": 0.70,
    "evidence_coverage": 0.80,
    "improvement": 0.20,
    "latency_seconds": 15.0,
}


def ensure_dirs() -> None:
    """Create the runtime directories if they don't exist."""
    STORES_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
