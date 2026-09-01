"""Retrieval layer: hybrid search + RRF fusion + KG multi-hop + rerank + lessons.

Pipeline (see DESIGN.md §6):
  1. detect question entities (string match against the KG vocabulary)
  2. dense vector search  +  BM25 keyword search  +  KG-neighbourhood chunks
  3. fuse the three ranked lists with Reciprocal Rank Fusion
  4. cross-encoder rerank the fused candidates -> final evidence
  5. attach deterministic KG facts (+ learned overrides) and relevant lessons
  6. compute a retrieval confidence used for graceful "insufficient evidence"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List

from rank_bm25 import BM25Okapi

from engine import classify, config, kg, memory, rerank
from engine.vectorstore import VectorStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Filtered from BM25 so groundedness reflects real content overlap, not stopwords
# (otherwise "what is the company policy?" matches on "the"/"is" and looks grounded).
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was",
    "were", "be", "been", "being", "it", "this", "that", "these", "those", "with", "as",
    "at", "by", "from", "what", "who", "why", "how", "when", "where", "which", "did",
    "do", "does", "done", "i", "you", "we", "they", "he", "she", "about", "into", "our",
    "your", "their", "its", "can", "could", "should", "would", "will", "company", "right",
    "now", "please", "tell", "me", "ask", "question",
}


def _tok(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class Evidence:
    source_id: str
    text: str
    source_type: str
    score: float           # dense cosine (0..1), used for confidence
    rerank_score: float | None = None


@dataclass
class Retrieval:
    question: str
    entities: List[str]
    evidence: List[Evidence]
    kg_facts: List[str]
    lessons: List[Dict[str, Any]] = field(default_factory=list)
    top_score: float = 0.0      # top dense cosine among final evidence
    bm25_top: float = 0.0       # top BM25 keyword score (0 == no lexical overlap)
    expert_answer: str = ""     # remembered expert answer to THIS exact question (V2)

    @property
    def evidence_ids(self) -> List[str]:
        return [e.source_id for e in self.evidence]


class _Index:
    """Lazily-loaded bundle: vector store + BM25 + chunk metadata."""

    def __init__(self) -> None:
        self.vstore = VectorStore.load(config.VECTOR_STORE_FILE, config.VECTOR_META_FILE)
        self.ids = self.vstore.ids
        self.texts = self.vstore.texts
        self.metas = self.vstore.metas
        self.id_to_text = dict(zip(self.ids, self.texts))
        self.id_to_meta = dict(zip(self.ids, self.metas))
        self.bm25 = BM25Okapi([_tok(t) for t in self.texts])


@lru_cache(maxsize=1)
def _index() -> _Index:
    return _Index()


def _rrf(ranked_lists: List[List[str]], k: int = config.RRF_K) -> Dict[str, float]:
    """Reciprocal Rank Fusion over several ranked id lists."""
    fused: Dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


def retrieve(question: str, use_lessons: bool = True) -> Retrieval:
    idx = _index()
    entities = kg.match_entities(question)

    # 1. dense
    dense_hits = idx.vstore.search(question, config.TOP_K_DENSE)
    dense_score = {hid: score for hid, score, _, _ in dense_hits}
    dense_list = [hid for hid, _, _, _ in dense_hits]

    # 2. BM25 keyword
    bm_scores = idx.bm25.get_scores(_tok(question))
    bm_ranked = sorted(range(len(idx.ids)), key=lambda i: -bm_scores[i])
    bm25_list = [idx.ids[i] for i in bm_ranked[: config.TOP_K_BM25] if bm_scores[i] > 0]

    # 3. KG multi-hop: chunks linked to the question's entity neighbourhood.
    # sorted() makes the candidate order deterministic (set iteration order otherwise
    # depends on PYTHONHASHSEED and would perturb RRF ranks run-to-run).
    kg_ids = sorted(kg.source_ids_for(entities, idx.metas, hops=2))

    # 4. fuse
    fused = _rrf([dense_list, bm25_list, kg_ids])
    fused_ids = sorted(fused, key=lambda d: -fused[d])[: config.RERANK_INPUT]

    # 5. rerank
    candidates = [(cid, idx.id_to_text[cid]) for cid in fused_ids if cid in idx.id_to_text]
    reranked = rerank.rerank(question, candidates)[: config.FINAL_K]

    evidence: List[Evidence] = []
    for cid, rscore in reranked:
        meta = idx.id_to_meta.get(cid, {})
        evidence.append(Evidence(
            source_id=cid,
            text=idx.id_to_text.get(cid, ""),
            source_type=meta.get("source_type", ""),
            score=round(float(dense_score.get(cid, 0.0)), 3),
            rerank_score=None if rscore is None else round(rscore, 3),
        ))

    # 6. Learning Memory (gated by use_lessons — this is what separates V1 from V2)
    # Classify the question so a lesson learned on a *different* same-type question
    # can be retrieved (approach transfer).
    query_type = classify.classify(question)["question_type"] if use_lessons else None
    lessons = memory.search_lessons(question, entities=entities, query_type=query_type) \
        if use_lessons else []

    # lesson-guided augmentation: ensure expert-recommended evidence is present.
    # Only for entity-matched lessons (same subject) — topic-only matches must not
    # drag in another question's evidence.
    present = {e.source_id for e in evidence}
    for lesson in lessons:
        if not lesson.get("_entity_match"):
            continue
        for rid in lesson.get("recommended_evidence_ids", []):
            if rid not in present and rid in idx.id_to_text:
                meta = idx.id_to_meta.get(rid, {})
                evidence.insert(0, Evidence(
                    source_id=rid,
                    text=idx.id_to_text[rid],
                    source_type=meta.get("source_type", ""),
                    score=round(float(dense_score.get(rid, 0.5)), 3),
                    rerank_score=None,
                ))
                present.add(rid)

    # base KG facts + learned overrides (overrides only with Learning Memory).
    base_facts = kg.facts_for(entities, hops=1)
    kg_facts = (memory.overrides_for(entities) + base_facts) if use_lessons else base_facts
    # If THIS exact question was taught before, recall the expert's own answer — the
    # same-question V1->V2 improvement the brief asks for. (Different questions never
    # match this, so it does not leak to them.)
    remembered = memory.answer_for(question) if use_lessons else ""

    top_score = max((e.score for e in evidence), default=0.0)
    bm25_top = float(max(bm_scores)) if len(bm_scores) else 0.0

    return Retrieval(
        question=question,
        entities=entities,
        evidence=evidence,
        kg_facts=kg_facts,
        lessons=lessons,
        top_score=round(top_score, 3),
        bm25_top=round(bm25_top, 3),
        expert_answer=remembered,
    )


def reset_index_cache() -> None:
    """Drop the cached index (call after re-ingesting)."""
    _index.cache_clear()
