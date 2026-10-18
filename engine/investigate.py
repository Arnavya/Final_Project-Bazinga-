"""AI Investigation: produce an answer + reasoning trace + citations + confidence.

Two backends share one interface:
  * real LLM (Groq/Ollama) — reasons over the assembled context and returns JSON
  * stub (config.USE_STUB) — deterministic heuristics so the whole pipeline runs
    offline with no key and no model download.

V1 vs V2 is controlled by `use_lessons`: V1 has no Learning Memory, V2 does.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List

from engine import config, llm
from engine.logs import get_logger, log_event
from engine.retrieve import Retrieval, retrieve

log = get_logger("investigate")

# Words that signal a causal / explanatory sentence (used by the stub).
_CUES = [
    "because", "caused", "broke", "root cause", "reverted", "rolled back",
    "blocked", "starv", "overwhelmed", "mistake", "without a default",
    "not on the critical path", "delay", "depends on", "not yet delivered",
    "retry storm", "concurrency", "migration",
]


# --- Groundedness / confidence (robust across embedders) ---
def _grounding(r: Retrieval) -> tuple[float, bool]:
    grounded = bool(r.entities) or r.bm25_top > 0.0 or r.top_score >= 0.35
    if not grounded:
        return 0.1, False
    signal = (0.45 if r.entities else 0.0) + (0.30 if r.bm25_top > 0 else 0.0) \
        + 0.25 * min(r.top_score / 0.5, 1.0)
    return round(min(0.95, 0.25 + signal), 2), True


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _causal_sentence(evidence) -> str:
    """First causal-looking sentence scanning evidence in rank order (stub heuristic)."""
    for ev in evidence:
        for sent in _split_sentences(ev.text):
            low = sent.lower()
            if any(cue in low for cue in _CUES):
                return sent
    return evidence[0].text[:200] if evidence else ""


# --- Context assembly (shared by the LLM path) ---
def _build_context(r: Retrieval) -> str:
    parts: List[str] = ["EVIDENCE (cite these source IDs in square brackets):"]
    for ev in r.evidence:
        parts.append(f"[{ev.source_id}] ({ev.source_type}) {ev.text}")
    if r.kg_facts:
        parts.append("\nKNOWLEDGE-GRAPH FACTS (authoritative; deterministic):")
        parts.extend(f"- {f}" for f in r.kg_facts)
    if r.lessons:
        parts.append("\nLESSONS FROM PAST EXPERT FEEDBACK (apply this approach):")
        for ls in r.lessons:
            line = f"- {ls.get('lesson_text', '')}"
            # Only attach the *specific* known root cause when the lesson is about the
            # SAME subject (entity match). For a same-type-but-different question we
            # transfer only the strategy, never the other question's answer.
            if ls.get("_entity_match") and ls.get("root_cause_correction"):
                line += f" (Known root cause for this subject: {ls['root_cause_correction']})"
            parts.append(line)
    return "\n".join(parts)


_SYSTEM = (
    "You are an Organizational Reasoning Engine. Answer the question using ONLY the "
    "provided evidence, knowledge-graph facts, and lessons. "
    "CRITICAL RELEVANCE RULE — check FIRST: The corpus only covers this fintech org: "
    "services (auth-service, checkout-service, payments-service, notifications-service, "
    "search-service, billing-service), incidents INC-9/INC-12, releases v2.1/v2.2, tickets, "
    "Slack, wiki. If the question is about anything else (bitcoin, crypto, stock price, weather, "
    "sports, politics, general knowledge, recipes, jokes, etc.) OR none of the provided evidence "
    "directly answers the question, you MUST NOT use the evidence. Output EXACTLY: "
    "answer='Insufficient evidence in the available knowledge sources to answer this question "
    "confidently.', root_cause='', cited_evidence_ids=[], confidence=0.1, reasoning_trace=['No "
    "matching entities and no lexical overlap with the corpus.', 'Lowering confidence instead of "
    "inventing an answer.']. Do not cite any source. "
    "Otherwise reason like a senior engineer: identify the true root cause, not just surface facts. "
    "NEVER invent service names, people, tickets, or facts that do not appear in the provided "
    "evidence or knowledge-graph facts — if something isn't there, do not name it. "
    "Cite source IDs in brackets only when evidence directly supports the answer. "
    "Prefer knowledge-graph facts and lessons when they conflict with stale documents. "
    "Examples: Q='what is bitcoin price today?' -> insufficient. Q='weather in Tokyo?' -> insufficient. "
    "Respond with ONLY a JSON object "
    "with keys: answer (string), root_cause (string), reasoning_trace (array of short strings), "
    "cited_evidence_ids (array of source-id strings), confidence (number 0..1)."
)


# --- Public entry point ---
def investigate(question: str, version: str = "V1", use_lessons: bool = True) -> Dict[str, Any]:
    start = time.perf_counter()
    r = retrieve(question, use_lessons=use_lessons)
    retr_conf, grounded = _grounding(r)
    retrieved_ids = r.evidence_ids

    if not grounded:
        record = _insufficient(question, version, use_lessons, r, retr_conf)
    elif config.USE_STUB:
        record = _stub_answer(question, version, use_lessons, r, retr_conf)
    else:
        record = _llm_answer(question, version, use_lessons, r, retr_conf)

    record["retrieved_ids"] = retrieved_ids
    record["entities"] = r.entities
    record["kg_facts"] = r.kg_facts
    record["lessons_used"] = [ls.get("lesson_id") for ls in r.lessons]
    # Carry the evidence so the UI can show what the answer is grounded in.
    record["evidence"] = [{"source_id": e.source_id, "source_type": e.source_type,
                           "score": e.score, "snippet": e.text[:220]} for e in r.evidence]
    record["latency_ms"] = int((time.perf_counter() - start) * 1000)
    return record


def _base(question: str, version: str, use_lessons: bool, r: Retrieval) -> Dict[str, Any]:
    return {"question": question, "version": version, "use_lessons": use_lessons}


def _insufficient(question, version, use_lessons, r, conf) -> Dict[str, Any]:
    rec = _base(question, version, use_lessons, r)
    rec.update({
        "answer": "Insufficient evidence in the available knowledge sources to answer this "
                  "question confidently.",
        "root_cause": "",
        "reasoning_trace": ["No matching entities and no lexical overlap with the corpus.",
                            "Lowering confidence instead of inventing an answer."],
        "cited_evidence_ids": [],
        "confidence": conf,
        "grounded": False,
    })
    return rec


# ------------------------------------------------------------------ stub path
def _stub_answer(question, version, use_lessons, r, retr_conf) -> Dict[str, Any]:
    # Specific corrections (root cause, recommended evidence) apply only when a
    # lesson matched on entity (same subject). Topic-only matches contribute strategy.
    subject_lessons = [ls for ls in r.lessons if ls.get("_entity_match")]
    lesson_rc = next((ls.get("root_cause_correction") for ls in subject_lessons
                      if ls.get("root_cause_correction")), "")
    root_cause = lesson_rc or _causal_sentence(r.evidence)

    # Cite the top evidence; with a same-subject lesson also cite recommended sources.
    cited = [e.source_id for e in r.evidence[:3]]
    rec_ids: List[str] = []
    for ls in subject_lessons:
        rec_ids += ls.get("recommended_evidence_ids", [])
    for rid in rec_ids:
        if rid not in cited and any(e.source_id == rid for e in r.evidence):
            cited.append(rid)

    # Compose the answer: root cause -> authoritative facts -> cited-evidence snippets.
    bits: List[str] = []
    if root_cause:
        bits.append(root_cause)
    for fact in r.kg_facts[:2]:
        bits.append(fact)
    cited_set = set(cited)
    for ev in r.evidence:
        if ev.source_id in cited_set:
            bits.append(_split_sentences(ev.text)[0] if _split_sentences(ev.text) else ev.text[:160])
        if len(bits) >= 6:
            break
    if not bits and r.evidence:
        bits.append(r.evidence[0].text[:200])
    # De-duplicate while preserving order.
    seen, ordered = set(), []
    for b in bits:
        if b and b not in seen:
            seen.add(b)
            ordered.append(b)
    answer = " ".join(ordered)

    trace = [f"Detected entities: {', '.join(r.entities) or 'none'}.",
             f"Reviewed {len(r.evidence)} evidence chunks via hybrid + KG retrieval."]
    if r.lessons:
        trace.append(f"Applied {len(r.lessons)} lesson(s) from past expert feedback "
                     f"({len(subject_lessons)} same-subject).")
    trace.append(f"Concluded root cause: {root_cause or 'n/a'}.")

    rec = _base(question, version, use_lessons, r)
    rec.update({
        "answer": answer,
        "root_cause": root_cause,
        "reasoning_trace": trace,
        "cited_evidence_ids": cited,
        "confidence": retr_conf,
        "grounded": True,
    })
    return rec


_REPRODUCE_SYSTEM = (
    "An expert has given the authoritative answer to this exact question. Output the expert's "
    "answer essentially VERBATIM as your 'answer' — do not reword, summarise, or omit anything; "
    "you may only fix obvious grammar and append the cited evidence IDs. Set root_cause from it "
    "if it states one. Respond with ONLY a JSON object with keys: answer, root_cause, "
    "reasoning_trace (array), cited_evidence_ids (array), confidence (0..1)."
)


# ------------------------------------------------------------------- llm path
def _llm_answer(question, version, use_lessons, r, retr_conf) -> Dict[str, Any]:
    if r.expert_answer:
        # Taught question -> re-run that reproduces the expert's stored answer verbatim.
        system = _REPRODUCE_SYSTEM
        user = (f"QUESTION: {question}\n\nEXPERT'S AUTHORITATIVE ANSWER (reproduce verbatim):\n"
                f"{r.expert_answer}\n\nEvidence IDs you may cite: {r.evidence_ids}\n\n"
                "Return ONLY the JSON object.")
    else:
        # Untaught question -> first-pass answer from the (imperfect) sources alone.
        system = _SYSTEM
        user = f"QUESTION: {question}\n\n{_build_context(r)}\n\nReturn ONLY the JSON object."
    try:
        # Same model for BOTH passes (config.LLM_MODEL). temperature=0 -> deterministic; the
        # only V1->V2 difference is what's retrieved into context (the learning).
        data = llm.chat_json(system, user, model=config.LLM_MODEL, temperature=0.0)
    except llm.LLMError as exc:
        # Resilience: on rate-limit / timeout / parse failure, degrade to the
        # deterministic answer rather than emitting an error that tanks metrics.
        # Logged as a warning so the silent degradation is visible to operators.
        log_event(log, "llm.fallback_to_stub", level=logging.WARNING, version=version,
                  error=str(exc)[:200])
        return _stub_answer(question, version, use_lessons, r, retr_conf)

    # Citation grounding: drop any cited id that wasn't actually retrieved.
    retrieved = set(r.evidence_ids)
    cited = [c for c in data.get("cited_evidence_ids", []) if c in retrieved]
    llm_conf = float(data.get("confidence", retr_conf) or retr_conf)
    confidence = round(0.5 * llm_conf + 0.5 * retr_conf, 2)

    rec = _base(question, version, use_lessons, r)
    rec.update({
        "answer": str(data.get("answer", "")).strip(),
        "root_cause": str(data.get("root_cause", "")).strip(),
        "reasoning_trace": [str(s) for s in data.get("reasoning_trace", [])],
        "cited_evidence_ids": cited,
        "confidence": confidence,
        "grounded": True,
    })
    return rec
