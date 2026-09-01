"""Learning Event creation: turn an expert-vs-AI gap into persisted learning.

Routing (see DESIGN.md §6):
  * strategy lesson  -> Learning Memory (retrieved for future questions)
  * factual correction (ownership etc.) -> a KG override (authoritative fact)
Both carry the expert-recommended evidence ids and the corrected root cause, so a
same-question re-run (V2) and future same-type questions both improve.
"""
from __future__ import annotations

from typing import Any, Dict, List

from engine import config, llm, memory


def _source_type(sid: str) -> str:
    for prefix, label in (("TICKET", "blocking tickets"), ("COMMIT", "commits / deploy logs"),
                          ("SLACK", "#releases / #incidents Slack threads"),
                          ("WIKI", "wiki docs"), ("INC", "incident records"),
                          ("REL", "release records")):
        if sid.startswith(prefix):
            return label
    return "source records"


def _missed_phrase(missing_ids: List[str], gold_ids: List[str]) -> str:
    ids = missing_ids or gold_ids
    types = sorted({_source_type(s) for s in ids})
    return ", ".join(types) if types else "tickets, commits and Slack threads"


def _template_lesson(scenario: Dict[str, Any], phrase: str) -> str:
    qtype = scenario.get("question_type", "this kind of")
    if qtype == "ownership":
        return (f"For {qtype} questions, trust the latest ticket or Slack reassignment over the "
                f"wiki page, which can be stale. Check {phrase} for the current owner.")
    return (f"For {qtype} questions, the decisive evidence is usually in {phrase}, not the "
            f"official wiki summary, which can be misleading. Trace the root cause through "
            f"those sources before concluding.")


_SYSTEM = (
    "You distill a reusable REASONING STRATEGY from a case where the AI's first answer "
    "differed from the human expert's. Describe HOW to approach this TYPE of question in "
    "general: which sources to consult first, what to cross-check, and what common trap to "
    "avoid. It must be transferable to OTHER questions of the same type — do NOT restate the "
    "specific answer or name this question's specific entities. One or two imperative "
    "sentences. Respond with ONLY a JSON object with key: lesson_text (string)."
)


def _llm_lesson_text(scenario: Dict[str, Any], gap: Dict[str, Any],
                     answer: Dict[str, Any], fallback: str) -> str:
    user = (
        f"QUESTION TYPE: {scenario.get('question_type')}\n"
        f"QUESTION: {scenario.get('question')}\n"
        f"AI'S FIRST ANSWER: {answer.get('answer')}\n"
        f"EXPERT (CORRECT) ANSWER: {scenario.get('gold_answer')}\n"
        f"EVIDENCE THE AI MISSED: {gap.get('missing_evidence_ids')}\n"
        f"GAP NOTES: {gap.get('narrative_diff')}\n\n"
        "What general approach would have led to the expert's answer? Return ONLY the JSON object."
    )
    try:
        data = llm.chat_json(_SYSTEM, user, model=config.LLM_SMALL_MODEL)
        text = str(data.get("lesson_text", "")).strip()
        return text or fallback
    except llm.LLMError:
        return fallback


def learn(scenario: Dict[str, Any], gap: Dict[str, Any], answer: Dict[str, Any]) -> Dict[str, Any]:
    qtype = scenario.get("question_type", "")
    gold_ev = scenario.get("gold_evidence_ids", [])
    missing = gap.get("missing_evidence_ids", [])
    phrase = _missed_phrase(missing, gold_ev)
    is_factual = qtype == "ownership"

    fallback_text = _template_lesson(scenario, phrase)
    lesson_text = fallback_text if config.USE_STUB \
        else _llm_lesson_text(scenario, gap, answer, fallback_text)

    entities = answer.get("entities", []) or scenario.get("topics", [])
    lesson = {
        "type": "factual" if is_factual else "strategy",
        "trigger": {
            "question_type": qtype,
            "topics": scenario.get("topics", []),
            "entities": entities,
        },
        "lesson_text": lesson_text,
        "root_cause_correction": scenario.get("gold_root_cause", ""),
        "recommended_evidence_ids": gold_ev,
        "missed_evidence_types": sorted({_source_type(s) for s in (missing or gold_ev)}),
        "source_question_id": scenario.get("id"),
    }

    action, lesson_id = memory.add_or_reinforce(lesson)
    lesson["lesson_id"] = lesson_id

    # Remember the expert's answer to THIS exact question -> a re-run (V2) reflects it.
    memory.add_answer(scenario.get("question", ""), scenario.get("gold_answer", ""))

    # Factual corrections also become an authoritative KG override, so they generalise
    # to OTHER questions about the same entity (e.g. a corrected owner).
    if is_factual:
        fact = f"AUTHORITATIVE (learned correction): {scenario.get('gold_answer', '')}"
        memory.add_override(entities, fact, source_question_id=scenario.get("id", ""))

    return {"action": action, "lesson": lesson}
