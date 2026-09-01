"""Gap Analysis: compare an AI answer against the human/expert answer.

Returns a GapReport with the project's success metrics. Evidence coverage is
computed deterministically in code (set overlap with the gold evidence). Answer
similarity and root-cause match use the LLM judge, or embedding heuristics in
stub mode.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine import config, embeddings, llm


def _coverage(cited: List[str], gold: List[str]) -> float:
    if not gold:
        return 1.0
    hit = len(set(cited) & set(gold))
    return round(hit / len(gold), 3)


_SYSTEM = (
    "You are a strict evaluator comparing an AI answer to the ground-truth expert answer. "
    "Score how well the AI answer matches the expert's meaning and whether it identifies the "
    "same root cause. Respond with ONLY a JSON object with keys: similarity (0..1), "
    "root_cause_match (0..1), missing_reasoning (array of short strings), "
    "factual_errors (array of short strings), narrative_diff (one short string)."
)


def judge(scenario: Dict[str, Any], answer: Dict[str, Any]) -> Dict[str, Any]:
    gold_answer = scenario.get("gold_answer", "")
    gold_rc = scenario.get("gold_root_cause", "")
    gold_ev = scenario.get("gold_evidence_ids", [])

    coverage = _coverage(answer.get("cited_evidence_ids", []), gold_ev)
    missing_ev = sorted(set(gold_ev) - set(answer.get("cited_evidence_ids", [])))

    if config.USE_STUB:
        report = _stub_judge(answer, gold_answer, gold_rc)
    else:
        report = _llm_judge(scenario, answer, gold_answer)

    report.update({
        "question_id": scenario.get("id"),
        "version": answer.get("version"),
        "evidence_coverage": coverage,
        "missing_evidence_ids": missing_ev,
        "confidence": answer.get("confidence"),
        "latency_ms": answer.get("latency_ms"),
    })
    return report


# ------------------------------------------------------------------ stub judge
def _stub_judge(answer: Dict[str, Any], gold_answer: str, gold_rc: str) -> Dict[str, Any]:
    sim_answer = embeddings.cosine(
        embeddings.embed_one(answer.get("answer", "")), embeddings.embed_one(gold_answer))
    if gold_rc:
        rc = embeddings.cosine(
            embeddings.embed_one(answer.get("root_cause", "")), embeddings.embed_one(gold_rc))
        rc_match: Optional[float] = round(max(0.0, rc), 3)
        similarity = round(max(0.0, 0.6 * sim_answer + 0.4 * rc), 3)
    else:
        rc_match = None
        similarity = round(max(0.0, sim_answer), 3)
    return {
        "similarity": similarity,
        "root_cause_match": rc_match,
        "missing_reasoning": [],
        "factual_errors": [],
        "narrative_diff": "stub judge: embedding-based similarity",
    }


# ------------------------------------------------------------------- llm judge
def _llm_judge(scenario: Dict[str, Any], answer: Dict[str, Any], gold_answer: str) -> Dict[str, Any]:
    user = (
        f"QUESTION: {scenario.get('question')}\n\n"
        f"EXPERT (ground truth) ANSWER:\n{gold_answer}\n\n"
        f"EXPERT ROOT CAUSE:\n{scenario.get('gold_root_cause') or '(n/a)'}\n\n"
        f"AI ANSWER:\n{answer.get('answer')}\n\n"
        f"AI ROOT CAUSE:\n{answer.get('root_cause') or '(none)'}\n\n"
        "Return ONLY the JSON object."
    )
    try:
        # temperature=0 -> stable, reproducible scoring (less run-to-run noise).
        data = llm.chat_json(_SYSTEM, user, model=config.LLM_MODEL, temperature=0.0)
    except llm.LLMError:
        # Fall back to the deterministic judge if the model misbehaves.
        return _stub_judge(answer, gold_answer, scenario.get("gold_root_cause", ""))

    gold_rc = scenario.get("gold_root_cause", "")
    # Blend the judge's (semantic) similarity with an embedding cosine. Weight the LLM
    # judge more: the metric is "similarity of MEANING", which the judge captures better
    # than raw text cosine (a faithful paraphrase has cosine well below 1.0).
    # Clamp every score to [0, 1] so a stray 0-100 value from the model can't exceed 100%.
    def _clip(x):
        return min(1.0, max(0.0, float(x)))

    emb = _clip(embeddings.cosine(
        embeddings.embed_one(answer.get("answer", "")), embeddings.embed_one(gold_answer)))
    similarity = round(min(1.0, 0.7 * _clip(data.get("similarity", 0.0)) + 0.3 * emb), 3)
    rc_match = round(_clip(data.get("root_cause_match", 0.0)), 3) if gold_rc else None
    return {
        "similarity": similarity,
        "root_cause_match": rc_match,
        "missing_reasoning": [str(s) for s in data.get("missing_reasoning", [])],
        "factual_errors": [str(s) for s in data.get("factual_errors", [])],
        "narrative_diff": str(data.get("narrative_diff", "")),
    }
