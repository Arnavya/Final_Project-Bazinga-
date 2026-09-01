"""Full lifecycle trace: question -> answer -> expert answer -> learning.

Prints every step in order, what it depends on, whether it could run in parallel,
its timing, and its result. (The current code runs sequentially; the PARALLEL tags
mark steps that are logically independent and could be parallelised.)

Usage:  python flow.py
"""
from __future__ import annotations

import time

import numpy as np

from engine import (classify, config, investigate, judge, kg, learn, memory,
                    rerank, retrieve)
from engine.retrieve import Evidence, Retrieval

Q = "Why was the v2.1 release delayed?"
EXPERT = ("The v2.1 release was delayed because database migration 0042 on payments-service "
          "added a NOT NULL column without a default, which broke payment writes. The release "
          "was held until the migration was reverted (COMMIT-a1b2). The QA backlog in the "
          "release notes was separate and not on the critical path.")


def line(n, name, dep, par, dt, result=""):
    print(f"  STEP {n:<4}{name:<34} {dt*1000:7.1f} ms")
    print(f"        depends on : {dep}")
    print(f"        parallel   : {par}")
    if result:
        print(f"        result     : {result}")
    print()


def main() -> None:
    memory.reset()
    idx = retrieve._index()
    print("=" * 80)
    print(f"QUESTION ASKED:  {Q}")
    print("=" * 80)
    print("\n############ PHASE A — QUESTION  ->  ANSWER ############\n")

    # 1 classify (LLM small)
    s = time.perf_counter(); cls = classify.classify(Q); dt = time.perf_counter() - s
    line(1, "Classify question type (LLM-8B)", "the question text",
         "INDEPENDENT — can run parallel with steps 2,3a,3b", dt,
         f"type={cls['question_type']} topics={cls['topics']}")

    # 2 entity match (KG string match)
    s = time.perf_counter(); ents = kg.match_entities(Q); dt = time.perf_counter() - s
    line(2, "Entity match (KG vocab)", "the question text",
         "INDEPENDENT — local; needed before step 3c", dt, f"{ents}")

    # 3a dense
    s = time.perf_counter(); dense = idx.vstore.search(Q, config.TOP_K_DENSE)
    dt = time.perf_counter() - s
    dense_score = {h[0]: h[1] for h in dense}
    line("3a", "Dense vector search (embeddings)", "the question (embedded)",
         "PARALLEL with 3b — independent retriever", dt,
         "top: " + ", ".join(f"{h[0]}({h[1]:.2f})" for h in dense[:4]))

    # 3b bm25
    s = time.perf_counter(); bm = idx.bm25.get_scores(retrieve._tok(Q))
    dt = time.perf_counter() - s
    order = [i for i in np.argsort(-bm) if bm[i] > 0]
    line("3b", "BM25 keyword search", "the question (tokens)",
         "PARALLEL with 3a — independent retriever", dt,
         "top: " + ", ".join(f"{idx.ids[i]}({bm[i]:.1f})" for i in order[:4]))

    # 3c kg multi-hop
    s = time.perf_counter(); kg_ids = sorted(kg.source_ids_for(ents, idx.metas, hops=2))
    dt = time.perf_counter() - s
    line("3c", "KG multi-hop (2 hops)", "step 2 (entities)",
         "DEPENDS on step 2; parallel with 3a/3b after that", dt, f"{kg_ids}")

    # 6 lessons (needs classify + entities) — independent of 3a/3b/3c
    s = time.perf_counter()
    lessons = memory.search_lessons(Q, entities=ents, query_type=cls["question_type"])
    dt = time.perf_counter() - s
    line(6, "Lesson retrieval (Learning Memory)", "steps 1 (type) + 2 (entities)",
         "INDEPENDENT of 3a/3b/3c — can run parallel", dt,
         f"{[l['lesson_id'] for l in lessons] or 'none yet (first ask)'}")

    # 4 RRF fusion (BARRIER on 3a,3b,3c)
    s = time.perf_counter()
    dense_list = [h[0] for h in dense]
    bm25_list = [idx.ids[i] for i in order[:config.TOP_K_BM25]]
    fused = retrieve._rrf([dense_list, bm25_list, kg_ids])
    fused_ids = sorted(fused, key=lambda d: -fused[d])[:config.RERANK_INPUT]
    dt = time.perf_counter() - s
    line(4, "RRF fusion", "BARRIER: needs 3a + 3b + 3c",
         "must wait for all three retrievers", dt, f"top: {fused_ids[:5]}")

    # 5 rerank (depends on 4)
    s = time.perf_counter()
    cands = [(cid, idx.id_to_text[cid]) for cid in fused_ids]
    reranked = rerank.rerank(Q, cands)[:config.FINAL_K]
    dt = time.perf_counter() - s
    line(5, "Cross-encoder rerank", "step 4 (fused candidates)",
         "sequential after fusion", dt, f"final {config.FINAL_K}: {[c[0] for c in reranked]}")

    # 7 assemble context (depends on 5 evidence + 6 lessons + kg facts)
    s = time.perf_counter()
    evidence = [Evidence(cid, idx.id_to_text[cid], idx.id_to_meta[cid]["source_type"],
                         round(dense_score.get(cid, 0.0), 3), rs) for cid, rs in reranked]
    kg_facts = kg.facts_for(ents, hops=1)
    r = Retrieval(Q, ents, evidence, kg_facts, lessons,
                  round(max((e.score for e in evidence), default=0.0), 3),
                  round(float(max(bm)) if len(bm) else 0.0, 3))
    retr_conf, grounded = investigate._grounding(r)
    dt = time.perf_counter() - s
    line(7, "Assemble LLM context", "steps 5 (evidence) + 6 (lessons) + KG facts",
         "BARRIER: needs retrieval + lessons", dt,
         f"{len(evidence)} evidence + {len(kg_facts)} facts + {len(lessons)} lessons; grounded={grounded}")

    # 8 LLM answer (depends on 7)
    s = time.perf_counter()
    rec = investigate._llm_answer(Q, "V1", False, r, retr_conf)
    rec["retrieved_ids"] = r.evidence_ids
    rec["entities"] = r.entities
    dt = time.perf_counter() - s
    line(8, "LLM synthesis (LLM-70B)", "step 7 (assembled context)",
         "sequential — the reasoning step", dt, "see ANSWER below")

    print("  ---------------- ANSWER PRODUCED ----------------")
    print(f"  ANSWER     : {rec['answer']}")
    print(f"  ROOT CAUSE : {rec['root_cause']}")
    print(f"  CITED      : {rec['cited_evidence_ids']}   (step 9: verified vs retrieved set)")
    print(f"  CONFIDENCE : {rec['confidence']}")

    # ---------------------------------------------------------------- PHASE B
    print("\n\n############ PHASE B — EXPERT ANSWER  ->  LEARNING ############\n")
    print(f"  EXPERT (human) ANSWER GIVEN:\n    {EXPERT}\n")

    scenario = {"id": "FLOW-1", "question": Q, "question_type": cls["question_type"],
                "topics": cls["topics"], "gold_answer": EXPERT, "gold_root_cause": "",
                "gold_evidence_ids": rec["retrieved_ids"][:3]}

    # 10 gap analysis (LLM)
    s = time.perf_counter(); gap = judge.judge(scenario, rec); dt = time.perf_counter() - s
    line(10, "Gap analysis / judge (LLM-70B)", "answer (step 8) + expert answer",
         "coverage is deterministic; similarity uses the LLM", dt,
         f"similarity={gap['similarity']} coverage={gap['evidence_coverage']} "
         f"missing={gap['missing_evidence_ids']}")

    # 11 distill lesson (LLM small) + route + dedup + persist
    s = time.perf_counter(); learned = learn.learn(scenario, gap, rec); dt = time.perf_counter() - s
    le = learned["lesson"]
    line(11, "Distill + route + persist lesson", "gap (step 10) + answer + expert",
         "LLM-8B distills; routing+dedup+write are local", dt,
         f"action={learned['action']} id={le['lesson_id']} type={le['type']}")
    print(f"        LESSON TEXT: {le['lesson_text']}")
    print(f"        WROTE      : stores/lessons.json"
          + ("  + stores/kg_overrides.json" if le["type"] == "factual" else "") + "\n")

    # 12 re-run V2 (repeats Phase A, now with the lesson available)
    s = time.perf_counter(); rec2 = investigate.investigate(Q, "V2", use_lessons=True)
    dt = time.perf_counter() - s
    line(12, "Re-run V2 (Phase A again)", "the new lesson (step 11)",
         "full investigate; lessons now retrieved in step 6", dt,
         f"lessons_applied={rec2['lessons_used']}")
    s = time.perf_counter(); gap2 = judge.judge(scenario, rec2); dt = time.perf_counter() - s
    line(13, "Re-judge V2", "V2 answer + expert answer", "same judge as step 10", dt,
         f"similarity {gap['similarity']} -> {gap2['similarity']}  "
         f"({gap2['similarity'] - gap['similarity']:+.2f})")

    print("  ---------------- LEARNING COMPLETE ----------------")
    print(f"  V2 ANSWER  : {rec2['answer']}")


if __name__ == "__main__":
    main()
