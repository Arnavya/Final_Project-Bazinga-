"""Unit tests for metric aggregation and success-criteria checks."""
from engine.metrics import _mean, aggregate


def test_mean_ignores_none():
    assert _mean([1.0, None, 3.0]) == 2.0


def test_mean_empty_is_none():
    assert _mean([]) is None
    assert _mean([None, None]) is None


def _gap(sim, rc, cov, latency=1000):
    return {"similarity": sim, "root_cause_match": rc,
            "evidence_coverage": cov, "latency_ms": latency}


def _result(v1, v2, warm=None):
    r = {"v1": _gap(*v1), "v2": _gap(*v2)}
    if warm is not None:
        r["v1_warm"] = _gap(*warm)
    return r


def test_aggregate_computes_improvement():
    results = [_result((0.6, 0.5, 0.5), (0.9, 0.9, 1.0)),
               _result((0.7, 0.6, 0.5), (0.9, 0.9, 1.0))]
    s = aggregate(results)
    assert s["n_scenarios"] == 2
    assert s["similarity_v1"] == 0.65
    assert s["similarity_v2"] == 0.9
    assert s["improvement"] == 0.25


def test_targets_met_reflects_thresholds():
    # strong V2 numbers should pass every target
    results = [_result((0.5, 0.5, 0.5), (0.9, 0.9, 0.9)),
               _result((0.5, 0.5, 0.5), (0.9, 0.9, 0.9))]
    s = aggregate(results)
    t = s["targets_met"]
    assert t["similarity>=0.75"] is True
    assert t["root_cause>=0.70"] is True
    assert t["evidence_coverage>=0.80"] is True
    assert t["improvement>=0.20"] is True   # 0.5 -> 0.9 = +0.4
    assert t["latency<15s"] is True


def test_generalization_lift_present_with_warm():
    results = [_result((0.6, 0.6, 0.6), (0.9, 0.9, 0.9), warm=(0.7, 0.7, 0.7))]
    s = aggregate(results)
    assert s["generalization_lift"] == 0.1  # warm 0.7 - cold 0.6


def test_criteria_has_six_entries():
    results = [_result((0.6, 0.6, 0.6), (0.9, 0.9, 0.9))]
    s = aggregate(results)
    assert len(s["criteria"]) == 6
