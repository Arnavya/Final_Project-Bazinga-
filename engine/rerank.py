"""Optional cross-encoder reranking (bge-reranker-base).

A cross-encoder reads (query, passage) together and scores relevance far more
accurately than bi-encoder cosine. If sentence-transformers isn't installed we
skip reranking and keep the fused order — the pipeline still works.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Tuple

from engine import config


@lru_cache(maxsize=1)
def _get_reranker():
    try:
        from sentence_transformers import CrossEncoder  # lazy import
        return CrossEncoder(config.RERANKER_MODEL)
    except Exception as exc:  # noqa: BLE001
        print(f"[rerank] cross-encoder unavailable ({exc}); keeping fused order.")
        return None


def rerank(query: str, candidates: List[Tuple[str, str]]) -> List[Tuple[str, Optional[float]]]:
    """candidates: list of (id, text). Returns [(id, score)] best-first.

    Score is None when no reranker is available (order preserved).
    """
    if not candidates:
        return []
    model = _get_reranker()
    if model is None:
        return [(cid, None) for cid, _ in candidates]
    pairs = [[query, text] for _, text in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip([c[0] for c in candidates], scores), key=lambda x: -float(x[1]))
    return [(cid, float(score)) for cid, score in ranked]
