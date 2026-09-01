"""Aggregate the per-scenario gap reports into the project's success metrics."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine import config


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """results: list of per-scenario dicts each with 'v1' and 'v2' gap reports."""
    v1_sim = [r["v1"]["similarity"] for r in results]
    v2_sim = [r["v2"]["similarity"] for r in results]
    v1_rc = [r["v1"]["root_cause_match"] for r in results]
    v2_rc = [r["v2"]["root_cause_match"] for r in results]
    v1_cov = [r["v1"]["evidence_coverage"] for r in results]
    v2_cov = [r["v2"]["evidence_coverage"] for r in results]
    latency = [r["v2"]["latency_ms"] for r in results if r["v2"].get("latency_ms") is not None]

    mean_v1 = _mean(v1_sim) or 0.0
    mean_v2 = _mean(v2_sim) or 0.0
    improvement = round(mean_v2 - mean_v1, 3)

    # Optional generalization signal: warm V1 (prior lessons only) vs cold V1.
    warm = [r["v1_warm"]["similarity"] for r in results if "v1_warm" in r]
    gen_lift = round((_mean(warm) or 0.0) - mean_v1, 3) if warm else None

    summary = {
        "n_scenarios": len(results),
        "similarity_v1": mean_v1,
        "similarity_v2": mean_v2,
        "improvement": improvement,
        "root_cause_v1": _mean(v1_rc),
        "root_cause_v2": _mean(v2_rc),
        "coverage_v1": _mean(v1_cov),
        "coverage_v2": _mean(v2_cov),
        "avg_latency_ms_v2": int(_mean(latency)) if latency else None,
        "generalization_lift": gen_lift,
    }
    summary["targets_met"] = _check_targets(summary)
    summary["criteria"] = _criteria(summary, results)
    return summary


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _criteria(s: Dict[str, Any], results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The 6 success metrics from the project brief, with target + achieved + pass."""
    t = config.TARGETS
    lat_s = (s["avg_latency_ms_v2"] / 1000.0) if s["avg_latency_ms_v2"] is not None else None
    ran = sum(1 for r in results if r["v2"].get("similarity") is not None)
    total = len(results)
    return [
        {"metric": "AI answer similarity to expert", "target": "≥ 75%",
         "achieved": _pct(s["similarity_v2"]), "met": (s["similarity_v2"] or 0) >= t["similarity"]},
        {"metric": "Root cause identification", "target": "≥ 70%",
         "achieved": _pct(s["root_cause_v2"]), "met": (s["root_cause_v2"] or 0) >= t["root_cause"]},
        {"metric": "Evidence coverage (expert's sources)", "target": "≥ 80%",
         "achieved": _pct(s["coverage_v2"]), "met": (s["coverage_v2"] or 0) >= t["evidence_coverage"]},
        {"metric": "Learning improvement (V1 → V2)", "target": "≥ 20%",
         "achieved": f"{(s['improvement'] or 0) * 100:+.0f}%",
         "met": (s["improvement"] or 0) >= t["improvement"]},
        {"metric": "Response time", "target": "< 15 s",
         "achieved": "—" if lat_s is None else f"{lat_s:.1f} s",
         "met": lat_s is not None and lat_s < t["latency_seconds"]},
        {"metric": "Test-scenario coverage", "target": "100%",
         "achieved": f"{ran}/{total} ({round(100 * ran / total) if total else 0}%)",
         "met": total > 0 and ran == total},
    ]


def _check_targets(s: Dict[str, Any]) -> Dict[str, bool]:
    t = config.TARGETS
    avg_lat_s = (s["avg_latency_ms_v2"] / 1000.0) if s["avg_latency_ms_v2"] is not None else None
    return {
        "similarity>=0.75": (s["similarity_v2"] or 0) >= t["similarity"],
        "root_cause>=0.70": (s["root_cause_v2"] or 0) >= t["root_cause"],
        "evidence_coverage>=0.80": (s["coverage_v2"] or 0) >= t["evidence_coverage"],
        "improvement>=0.20": (s["improvement"] or 0) >= t["improvement"],
        "latency<15s": (avg_lat_s is not None and avg_lat_s < t["latency_seconds"]),
    }
