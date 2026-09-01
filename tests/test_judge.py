"""Unit tests for the deterministic evidence-coverage metric."""
from engine.judge import _coverage


def test_coverage_full_overlap():
    assert _coverage(["A", "B"], ["A", "B"]) == 1.0


def test_coverage_partial():
    # 1 of 2 gold ids cited -> 0.5
    assert _coverage(["A", "X"], ["A", "B"]) == 0.5


def test_coverage_ignores_extra_citations():
    # citing extra (non-gold) ids does not lower coverage
    assert _coverage(["A", "B", "C", "D"], ["A", "B"]) == 1.0


def test_coverage_empty_gold_is_full():
    # nothing required -> trivially covered
    assert _coverage([], []) == 1.0


def test_coverage_none_cited():
    assert _coverage([], ["A", "B"]) == 0.0
