"""Unit tests for the retrieval primitives: tokenisation and RRF fusion."""
from engine import config
from engine.retrieve import _rrf, _tok


def test_tok_lowercases_and_drops_stopwords():
    toks = _tok("Why WAS the Release delayed?")
    assert "release" in toks
    assert "delayed" in toks
    # stopwords ("why", "was", "the") must be filtered out
    assert "the" not in toks and "was" not in toks and "why" not in toks


def test_tok_strips_punctuation():
    assert _tok("payments-service, INC-9!") == ["payments", "service", "inc", "9"]


def test_rrf_rewards_top_ranks():
    # a doc ranked first in both lists must beat a doc ranked lower in one.
    fused = _rrf([["a", "b", "c"], ["a", "c", "b"]])
    assert fused["a"] > fused["b"]
    assert fused["a"] > fused["c"]


def test_rrf_uses_configured_constant():
    # single list, single doc at rank 0 -> exactly 1/(RRF_K + 1)
    fused = _rrf([["only"]])
    assert fused["only"] == 1.0 / (config.RRF_K + 1)


def test_rrf_accumulates_across_lists():
    # a doc present in two lists scores higher than one present in a single list.
    fused = _rrf([["x", "y"], ["x", "z"]])
    assert fused["x"] > fused["y"]
    assert fused["x"] > fused["z"]
