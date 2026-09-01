"""Classify a question into a type + topics so lessons key by *kind* of question.

This is what lets a strategy learned on one question be retrieved for a *different*
question of the same type (approach transfer, not memorization). Uses the small
LLM when available, else keyword heuristics.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, List

from engine import config, llm

TAXONOMY = ["release_delay", "incident_rca", "ownership", "milestone_blocker",
            "design_decision", "impact_analysis", "general"]

_SYSTEM = (
    "Classify the user's question by the KIND OF REASONING it needs, not surface words. "
    "Choose exactly one question_type from: " + ", ".join(TAXONOMY) + ". "
    "Use 'impact_analysis' for ANY 'what/who is affected if X fails / is late / has an outage / "
    "is delayed' question (tracing dependencies and downstream blast radius), regardless of the "
    "failure verb. Also extract 2-4 lowercase topic keywords. Respond with ONLY a JSON object: "
    '{"question_type": "...", "topics": ["...", "..."]}.'
)


def _stub(question: str) -> Dict[str, object]:
    q = question.lower()
    if any(w in q for w in ["affected", "affect", "impact", "blast radius", "downstream",
                            "what else", "what happens if", "knock-on", "cascade"]):
        qt = "impact_analysis"
    elif any(w in q for w in ["own", "owner", "responsible", "contact", "ask about", "maintain"]):
        qt = "ownership"
    elif any(w in q for w in ["caus", "incident", "root cause", "went wrong", "fail", "broke", "outage"]):
        qt = "incident_rca"
    elif any(w in q for w in ["delay", "late", "slip", "behind schedule"]):
        qt = "release_delay"
    elif any(w in q for w in ["block", "milestone", "depend", "holding up", "waiting on"]):
        qt = "milestone_blocker"
    elif any(w in q for w in ["why", "decision", "change", "design", "switch", "move away"]):
        qt = "design_decision"
    else:
        qt = "general"
    topics = [t for t in re.findall(r"[a-z0-9-]+", q) if len(t) > 3][:5]
    return {"question_type": qt, "topics": topics}


@lru_cache(maxsize=256)
def classify(question: str) -> Dict[str, object]:
    if config.USE_STUB:
        return _stub(question)
    try:
        data = llm.chat_json(_SYSTEM, f"QUESTION: {question}", model=config.LLM_SMALL_MODEL)
        qt = str(data.get("question_type", "general")).strip()
        if qt not in TAXONOMY:
            qt = "general"
        topics: List[str] = [str(t).lower() for t in data.get("topics", [])][:5]
        return {"question_type": qt, "topics": topics or _stub(question)["topics"]}
    except llm.LLMError:
        return _stub(question)
