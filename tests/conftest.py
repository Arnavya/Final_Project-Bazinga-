"""Test configuration.

Force the dependency-free, offline backends BEFORE any engine module is imported,
so the unit tests never download a model or make a network call:
  * EMBEDDING_MODEL=hashing -> numpy hashing embedder (no sentence-transformers)
  * LLM_PROVIDER=stub       -> deterministic heuristics (no API key, no HTTP)
"""
import os

os.environ.setdefault("EMBEDDING_MODEL", "hashing")
os.environ.setdefault("LLM_PROVIDER", "stub")
