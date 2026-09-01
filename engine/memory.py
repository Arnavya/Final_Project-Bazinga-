"""Learning Memory: persistent, retrievable lessons + knowledge-graph overrides.

This is where learning lives. Lessons (transferable reasoning patterns) are
stored as data and retrieved by semantic similarity for *any* future question.
Factual corrections are kept as KG overrides — authoritative facts injected into
context that supersede stale source text.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from engine import config, embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> set:
    return set(_TOKEN_RE.findall(text.lower()))


# ------------------------------------------------------------------ lessons
def load_lessons() -> List[Dict[str, Any]]:
    if not config.LESSONS_FILE.exists():
        return []
    return json.loads(config.LESSONS_FILE.read_text(encoding="utf-8"))


def save_lessons(lessons: List[Dict[str, Any]]) -> None:
    config.ensure_dirs()
    config.LESSONS_FILE.write_text(json.dumps(lessons, indent=2), encoding="utf-8")


def _retrieval_key(lesson: Dict[str, Any]) -> str:
    """Text used to embed a lesson for retrieval (lesson + its trigger topics)."""
    trig = lesson.get("trigger", {})
    topics = " ".join(trig.get("topics", []))
    return f"{trig.get('question_type', '')} {topics} {lesson.get('lesson_text', '')}".strip()


def search_lessons(
    question: str,
    entities: Optional[List[str]] = None,
    query_type: Optional[str] = None,
    k: int = config.LESSON_TOP_K,
    threshold: float = config.LESSON_SIM_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Return up to k lessons relevant to the question (each with a `_score`).

    Combines four signals and takes the max, so retrieval is robust even with a
    weak fallback embedder:
      * semantic — embedding cosine of the question vs the lesson key
      * entity   — question entities intersect the lesson's trigger entities (same subject)
      * type     — the classified question_type matches the lesson's (approach transfer!)
      * topic    — lexical overlap of the lesson's topics with the question

    `_entity_match` is set ONLY on an entity match, gating whether the caller may apply
    the lesson's *specific* corrections (recommended evidence, root cause) vs only its
    general strategy text.
    """
    lessons = load_lessons()
    if not lessons:
        return []
    qtokens = _tok(question)
    qents = set(entities or [])

    keys = [_retrieval_key(l) for l in lessons]
    mat = embeddings.embed(keys)                       # normalised
    q = embeddings.embed_one(question)
    qn = np.linalg.norm(q)
    if qn > 0:
        q = q / qn
    emb_scores = mat @ q

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for i, lesson in enumerate(lessons):
        trig = lesson.get("trigger", {})
        ent_score = 1.0 if qents & set(trig.get("entities", [])) else 0.0
        type_score = 0.85 if query_type and trig.get("question_type") == query_type else 0.0
        topic_tokens = set()
        for t in trig.get("topics", []):
            topic_tokens |= _tok(t)
        topic_score = (len(topic_tokens & qtokens) / len(topic_tokens)) if topic_tokens else 0.0
        score = max(float(emb_scores[i]), ent_score, type_score, topic_score)
        if score >= threshold:
            out = dict(lesson)
            out["_score"] = round(score, 3)
            out["_entity_match"] = ent_score >= 1.0
            scored.append((score, out))
    scored.sort(key=lambda x: -x[0])
    return [l for _, l in scored[:k]]


def add_or_reinforce(lesson: Dict[str, Any]) -> Tuple[str, str]:
    """Add a new lesson, or reinforce a near-duplicate of the same question type.

    Returns (action, lesson_id) where action is "added" or "reinforced".
    """
    lessons = load_lessons()
    new_key = _retrieval_key(lesson)
    if lessons:
        keys = [_retrieval_key(l) for l in lessons]
        mat = embeddings.embed(keys)
        v = embeddings.embed_one(new_key)
        vn = np.linalg.norm(v)
        if vn > 0:
            v = v / vn
        sims = mat @ v
        j = int(np.argmax(sims))
        trig_new = lesson.get("trigger", {})
        trig_old = lessons[j].get("trigger", {})
        same_type = trig_old.get("question_type") == trig_new.get("question_type")
        new_ents, old_ents = set(trig_new.get("entities", [])), set(trig_old.get("entities", []))
        # Only merge when it's truly the same correction: same type AND overlapping
        # entities (or both entity-free). Otherwise per-question corrections are kept.
        same_subject = bool(new_ents & old_ents) or (not new_ents and not old_ents)
        if float(sims[j]) >= config.LESSON_DEDUP_THRESHOLD and same_type and same_subject:
            lessons[j]["reinforced_count"] = lessons[j].get("reinforced_count", 1) + 1
            save_lessons(lessons)
            return "reinforced", lessons[j]["lesson_id"]

    lesson_id = f"LE-{len(lessons) + 1:03d}"
    lesson["lesson_id"] = lesson_id
    lesson.setdefault("reinforced_count", 1)
    lesson.setdefault("created_ts", time.time())
    lessons.append(lesson)
    save_lessons(lessons)
    return "added", lesson_id


# --------------------------------------------------------------- KG overrides
def load_overrides() -> List[Dict[str, Any]]:
    if not config.KG_OVERRIDES_FILE.exists():
        return []
    return json.loads(config.KG_OVERRIDES_FILE.read_text(encoding="utf-8"))


def save_overrides(overrides: List[Dict[str, Any]]) -> None:
    config.ensure_dirs()
    config.KG_OVERRIDES_FILE.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


def add_override(entities: List[str], fact_text: str, source_question_id: str = "") -> None:
    overrides = load_overrides()
    if any(o["fact_text"] == fact_text for o in overrides):
        return
    overrides.append({
        "entities": sorted({e for e in entities if e}),
        "fact_text": fact_text,
        "source_question_id": source_question_id,
    })
    save_overrides(overrides)


def overrides_for(entities: List[str]) -> List[str]:
    """Authoritative correction facts whose entities intersect the question's."""
    ents = set(entities)
    return [o["fact_text"] for o in load_overrides() if ents.intersection(o.get("entities", []))]


# --------------------------------------------------------- exact-question answers
def _norm(q: str) -> str:
    return " ".join(q.lower().split())


def load_answers() -> Dict[str, str]:
    if not config.ANSWERS_FILE.exists():
        return {}
    return json.loads(config.ANSWERS_FILE.read_text(encoding="utf-8"))


def add_answer(question: str, expert_answer: str) -> None:
    """Remember the expert's answer to THIS exact question (for same-question V2)."""
    if not question or not expert_answer:
        return
    answers = load_answers()
    answers[_norm(question)] = expert_answer
    config.ensure_dirs()
    config.ANSWERS_FILE.write_text(json.dumps(answers, indent=2), encoding="utf-8")


def answer_for(question: str) -> str:
    """The expert answer if this EXACT question was taught before, else ''."""
    return load_answers().get(_norm(question), "")


def reset() -> None:
    """Clear all learned state (used to start a clean benchmark run)."""
    for f in (config.LESSONS_FILE, config.KG_OVERRIDES_FILE, config.ANSWERS_FILE):
        if f.exists():
            f.unlink()
