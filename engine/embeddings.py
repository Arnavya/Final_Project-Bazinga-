"""Text embeddings with a graceful fallback.

Primary backend: sentence-transformers (BAAI/bge-small-en-v1.5) — good quality,
local, free. If it (or torch) isn't installed, or EMBEDDING_MODEL == "hashing",
we fall back to a dependency-free numpy hashing embedder so the whole pipeline
still runs offline. All vectors are L2-normalised, so cosine similarity is a dot
product.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import List

import numpy as np

from engine import config

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _stable_hash(s: str) -> int:
    """Process-independent hash (Python's built-in hash() is randomized per run)."""
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


class _HashingEmbedder:
    """Dependency-free fallback: hashed bag-of-words with sublinear TF, L2-normalised.

    Not as strong as a real sentence encoder, but deterministic and good enough to
    exercise the full retrieval pipeline with no downloads.
    """

    def __init__(self, dim: int = config.HASHING_DIM):
        self.dim = dim
        self.name = "hashing-fallback"

    def encode(self, texts: List[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            counts: dict[int, float] = {}
            for tok in _tokenize(text):
                # Two hashed slots per token reduce collision damage.
                h1 = _stable_hash("a:" + tok) % self.dim
                h2 = _stable_hash("b:" + tok) % self.dim
                counts[h1] = counts.get(h1, 0.0) + 1.0
                counts[h2] = counts.get(h2, 0.0) + 1.0
            for idx, c in counts.items():
                vecs[i, idx] = 1.0 + np.log(c)  # sublinear term frequency
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs


class _STEmbedder:
    """sentence-transformers backend."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # lazy import

        self.model = SentenceTransformer(model_name)
        self.name = model_name

    def encode(self, texts: List[str]) -> np.ndarray:
        return np.asarray(
            self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )


@lru_cache(maxsize=1)
def get_embedder():
    """Return a singleton embedder, preferring sentence-transformers."""
    if config.EMBEDDING_MODEL.lower() != "hashing":
        try:
            return _STEmbedder(config.EMBEDDING_MODEL)
        except Exception as exc:  # noqa: BLE001 - any import/load failure -> fallback
            print(f"[embeddings] sentence-transformers unavailable ({exc}); "
                  f"using hashing fallback.")
    return _HashingEmbedder()


def embed(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    return get_embedder().encode(texts)


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for (possibly un-normalised) 1-D vectors."""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
