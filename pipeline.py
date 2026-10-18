"""End-to-end orchestration of the learning loop (shared by CLI + dashboard).

For each scenario:
  V1 (cold)   = investigate with NO Learning Memory      -> the naive baseline
  V1 (warm)   = investigate WITH prior lessons only       -> generalization signal
  learn       = capture the expert-vs-AI gap as a lesson  -> persist
  V2          = investigate WITH Learning Memory (incl. this lesson) -> improved
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List

from engine import classify, config, investigate, judge, learn, memory, metrics, store
from engine.logs import get_logger, log_event

log = get_logger("pipeline")


def _qid(question: str) -> str:
    """Short stable fingerprint so logs can correlate a question without storing its text."""
    return hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()[:12]


def load_scenarios() -> List[Dict[str, Any]]:
    return json.loads(config.SCENARIOS_FILE.read_text(encoding="utf-8"))


def run_one(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single scenario through the full V1 -> learn -> V2 loop."""
    q = scenario["question"]

    a1_cold = investigate.investigate(q, version="V1", use_lessons=False)
    a1_warm = investigate.investigate(q, version="V1-warm", use_lessons=True)

    g1 = judge.judge(scenario, a1_cold)
    g1_warm = judge.judge(scenario, a1_warm)

    learned = learn.learn(scenario, g1, a1_cold)

    a2 = investigate.investigate(q, version="V2", use_lessons=True)
    g2 = judge.judge(scenario, a2)

    return {
        "id": scenario["id"],
        "question": q,
        "question_type": scenario.get("question_type"),
        "gold_answer": scenario.get("gold_answer"),
        "gold_root_cause": scenario.get("gold_root_cause"),
        "gold_evidence_ids": scenario.get("gold_evidence_ids"),
        "answer_v1": a1_cold,
        "answer_v2": a2,
        "v1": g1,
        "v1_warm": g1_warm,
        "v2": g2,
        "learned": learned,
    }


def run_benchmark(reset: bool = True) -> Dict[str, Any]:
    """Run all scenarios sequentially so lessons accumulate; return results + summary."""
    start = time.perf_counter()
    if reset:
        memory.reset()  # start from a blank Learning Memory for a fair cold baseline
    scenarios = load_scenarios()
    results = [run_one(s) for s in scenarios]
    summary = metrics.aggregate(results)
    store.save_benchmark(results)  # persist reasoning history; summary recomputed on load
    log_event(log, "benchmark.completed", scenarios=len(results),
              duration_ms=int((time.perf_counter() - start) * 1000))
    return {"results": results, "summary": summary}


# --- Live "Ask" mode (free-form questions; optional human-in-the-loop learning) ---
def ask(question: str) -> Dict[str, Any]:
    """Answer any free-form question using the full Learning Memory."""
    start = time.perf_counter()
    try:
        answer = investigate.investigate(question, version="ask", use_lessons=True)
    except Exception:
        log.exception("ask.failed", extra={"event": "ask.failed", "qid": _qid(question)})
        raise
    log_event(log, "ask.completed", qid=_qid(question), q_len=len(question),
              latency_ms=int((time.perf_counter() - start) * 1000),
              grounded=answer.get("grounded"), confidence=answer.get("confidence"),
              provider="stub" if config.USE_STUB else config.LLM_PROVIDER)
    return answer


def teach(question: str, expert_answer: str, ai_answer: Dict[str, Any]) -> Dict[str, Any]:
    """Live human-in-the-loop: capture the expert answer, learn, and re-run (V2)."""
    cls = classify.classify(question)
    is_ownership = cls["question_type"] == "ownership"
    scenario = {
        "id": f"ASK-{len(store.load_ask_log()) + 1:03d}",
        "question": question,
        "question_type": cls["question_type"],
        "topics": cls["topics"],
        "gold_answer": expert_answer,
        "gold_root_cause": "",
        # best-effort: treat the sources the AI consulted as the recommended set
        "gold_evidence_ids": ai_answer.get("retrieved_ids", [])[:3],
    }
    gap_v1 = judge.judge(scenario, ai_answer)
    learned = learn.learn(scenario, gap_v1, ai_answer)
    # learn() now stores the exact-question answer memory, so a same-question re-run
    # reflects the expert answer (no separate override needed here).

    answer_v2 = investigate.investigate(question, version="ask-v2", use_lessons=True)
    gap_v2 = judge.judge(scenario, answer_v2)

    event = {
        "question": question, "expert_answer": expert_answer,
        "similarity_v1": gap_v1["similarity"], "similarity_v2": gap_v2["similarity"],
        "lesson": learned["lesson"]["lesson_text"], "action": learned["action"],
    }
    store.append_ask(event)
    log_event(log, "teach.completed", qid=_qid(question), action=learned["action"],
              similarity_v1=gap_v1["similarity"], similarity_v2=gap_v2["similarity"])
    return {"gap_v1": gap_v1, "learned": learned, "answer_v2": answer_v2, "gap_v2": gap_v2}
