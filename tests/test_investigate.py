"""Unit tests for investigation helpers: sentence split, causal cue, grounding."""
from engine.investigate import _causal_sentence, _grounding, _split_sentences
from engine.retrieve import Evidence, Retrieval


def _retrieval(entities=None, bm25_top=0.0, evidence=None):
    return Retrieval(
        question="q", entities=entities or [],
        evidence=evidence or [], kg_facts=[], bm25_top=bm25_top,
        top_score=(evidence[0].score if evidence else 0.0),
    )


def test_split_sentences():
    out = _split_sentences("First. Second! Third?")
    assert out == ["First.", "Second!", "Third?"]


def test_causal_sentence_picks_cue():
    ev = [Evidence("S1", "The sky is blue. It broke because of a null default.", "slack", 0.4)]
    assert "because" in _causal_sentence(ev).lower()


def test_causal_sentence_falls_back_to_first():
    ev = [Evidence("S1", "Just a plain statement with no cue words here.", "wiki", 0.4)]
    # no causal cue -> returns the leading text rather than nothing
    assert _causal_sentence(ev).startswith("Just a plain statement")


def test_grounding_false_when_no_signal():
    conf, grounded = _grounding(_retrieval(entities=[], bm25_top=0.0))
    assert grounded is False
    assert conf <= 0.1


def test_grounding_true_with_entity_match():
    conf, grounded = _grounding(_retrieval(entities=["payments-service"]))
    assert grounded is True
    assert conf > 0.1


def test_grounding_true_with_lexical_overlap():
    conf, grounded = _grounding(_retrieval(bm25_top=2.5))
    assert grounded is True
