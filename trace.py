"""Explainability tool: walk ONE question through every retrieval stage and show
which source contributes what, and how the final answer is constructed.

Usage:  python trace.py                       # default question
        python trace.py "your question here"
"""
from __future__ import annotations

import sys

import numpy as np

from engine import config, investigate, kg, rerank, retrieve


def snip(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return (text[:n] + "…") if len(text) > n else text


def main() -> None:
    q = sys.argv[1] if len(sys.argv) > 1 else "Why was the v2.1 release delayed?"
    idx = retrieve._index()
    print(f"QUESTION: {q}\n" + "=" * 78)

    # 1. ENTITIES (knowledge-graph string match)
    ents = kg.match_entities(q)
    print(f"\n[1] ENTITY MATCH (KG vocab)  -> {ents}")

    # 2. DENSE / vector (semantic) search
    dense = idx.vstore.search(q, config.TOP_K_DENSE)
    print("\n[2] DENSE (embeddings — meaning):")
    for hid, score, _, meta in dense[:6]:
        print(f"    {score:5.2f}  {hid:<22}{meta['source_type']:<9} {snip(idx.id_to_text[hid])}")

    # 3. BM25 (keyword) search
    bm = idx.bm25.get_scores(retrieve._tok(q))
    order = [i for i in np.argsort(-bm) if bm[i] > 0]
    print("\n[3] BM25 (keywords — exact terms like 'v2.1'):")
    for i in order[:6]:
        print(f"    {bm[i]:5.2f}  {idx.ids[i]:<22}{idx.metas[i]['source_type']:<9} {snip(idx.texts[i])}")

    # 4. KG multi-hop (relationships)
    kg_ids = sorted(kg.source_ids_for(ents, idx.metas, hops=2))
    print("\n[4] KG MULTI-HOP (2 hops from entities -> linked chunks):")
    print(f"    candidate chunks: {kg_ids}")
    print("    derived facts:")
    for f in kg.facts_for(ents, hops=1)[:6]:
        print(f"      - {f}")

    # 5. RRF fusion of the three lists
    dense_list = [h[0] for h in dense]
    bm25_list = [idx.ids[i] for i in order[:config.TOP_K_BM25]]
    fused = retrieve._rrf([dense_list, bm25_list, kg_ids])
    fused_ids = sorted(fused, key=lambda d: -fused[d])[:config.RERANK_INPUT]
    print("\n[5] RRF FUSION (merge dense+BM25+KG by rank):")
    for cid in fused_ids[:8]:
        tag = []
        if cid in dense_list:
            tag.append("dense")
        if cid in bm25_list:
            tag.append("bm25")
        if cid in kg_ids:
            tag.append("kg")
        print(f"    {fused[cid]:.3f}  {cid:<22}[{','.join(tag)}]")

    # 6. Cross-encoder rerank -> final evidence
    cands = [(cid, idx.id_to_text[cid]) for cid in fused_ids]
    reranked = rerank.rerank(q, cands)[:config.FINAL_K]
    print(f"\n[6] RERANK (cross-encoder -> top {config.FINAL_K} evidence to the LLM):")
    for cid, rscore in reranked:
        s = f"{rscore:6.2f}" if rscore is not None else "   -  "
        print(f"    {s}  {cid:<22}{idx.id_to_meta[cid]['source_type']:<9} {snip(idx.id_to_text[cid])}")

    # 7. LLM answer
    print("\n[7] LLM SYNTHESIS (reads the evidence above + KG facts -> answer):")
    rec = investigate.investigate(q, use_lessons=False)
    print(f"    ANSWER     : {rec['answer']}")
    print(f"    ROOT CAUSE : {rec['root_cause']}")
    print(f"    CITED      : {rec['cited_evidence_ids']}")
    print(f"    CONFIDENCE : {rec['confidence']}")
    print("    REASONING  :")
    for step in rec["reasoning_trace"]:
        print(f"      - {step}")


if __name__ == "__main__":
    main()
