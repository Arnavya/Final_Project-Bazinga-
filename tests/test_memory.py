"""Unit tests for Learning Memory helpers that don't touch disk."""
from engine.memory import _norm, _retrieval_key


def test_norm_collapses_whitespace_and_case():
    assert _norm("  Why  was  THE   release   delayed? ") == "why was the release delayed?"


def test_norm_is_idempotent():
    once = _norm("Who OWNS  notifications-service?")
    assert _norm(once) == once


def test_retrieval_key_includes_type_topics_and_text():
    lesson = {
        "trigger": {"question_type": "ownership", "topics": ["notifications", "owner"]},
        "lesson_text": "Trust the latest reassignment over the wiki.",
    }
    key = _retrieval_key(lesson)
    assert "ownership" in key
    assert "notifications" in key
    assert "Trust the latest reassignment" in key
