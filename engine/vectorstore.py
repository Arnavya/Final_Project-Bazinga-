"""A small, dependency-light vector store (numpy matrix + cosine search).

Transparent on purpose — explainability is a project goal, and this avoids any
heavy/fragile vector-DB dependency while running identically on Linux and macOS.
Vectors are assumed L2-normalised (see embeddings.py), so cosine == dot product.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from engine import embeddings


class VectorStore:
    def __init__(self) -> None:
        self.ids: List[str] = []
        self.texts: List[str] = []
        self.metas: List[Dict[str, Any]] = []
        self._matrix: Optional[np.ndarray] = None  # shape (N, D), normalised

    # ------------------------------------------------------------------ build
    def add(self, ids: List[str], texts: List[str], metas: List[Dict[str, Any]]) -> None:
        vecs = embeddings.embed(texts)
        self.ids.extend(ids)
        self.texts.extend(texts)
        self.metas.extend(metas)
        self._matrix = vecs if self._matrix is None else np.vstack([self._matrix, vecs])

    # ----------------------------------------------------------------- search
    def search(self, query: str, k: int = 10) -> List[Tuple[str, float, str, Dict[str, Any]]]:
        """Return up to k (id, score, text, meta) tuples, most similar first."""
        if self._matrix is None or len(self.ids) == 0:
            return []
        q = embeddings.embed_one(query)
        qn = np.linalg.norm(q)
        if qn > 0:
            q = q / qn
        scores = self._matrix @ q  # cosine because rows are normalised
        k = min(k, len(self.ids))
        top = np.argsort(-scores)[:k]
        return [(self.ids[i], float(scores[i]), self.texts[i], self.metas[i]) for i in top]

    # ----------------------------------------------------------------- persist
    def save(self, matrix_file: Path, meta_file: Path) -> None:
        matrix_file.parent.mkdir(parents=True, exist_ok=True)
        mat = self._matrix if self._matrix is not None else np.zeros((0, 1), dtype=np.float32)
        np.savez_compressed(matrix_file, matrix=mat)
        meta_file.write_text(
            json.dumps({"ids": self.ids, "texts": self.texts, "metas": self.metas}),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, matrix_file: Path, meta_file: Path) -> "VectorStore":
        store = cls()
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        store.ids = data["ids"]
        store.texts = data["texts"]
        store.metas = data["metas"]
        store._matrix = np.load(matrix_file)["matrix"]
        return store

    def __len__(self) -> int:
        return len(self.ids)
