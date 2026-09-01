"""Run the full benchmark: every scenario through V1 -> learn -> V2, with a report.

Usage:
    python run_all.py
"""
from __future__ import annotations

from engine import config
from pipeline import run_benchmark


def _fmt(x) -> str:
    return "  -  " if x is None else f"{x:.2f}"


def main() -> None:
    print(f"LLM provider: {config.LLM_PROVIDER}"
          f"{' (stub/offline — no key)' if config.USE_STUB else ''}\n")

    out = run_benchmark(reset=True)
    results, s = out["results"], out["summary"]

    # Per-scenario table.
    print(f"{'ID':<6}{'type':<18}{'sim V1':>8}{'sim V2':>8}{'Δsim':>7}"
          f"{'rc V2':>7}{'cov V2':>8}")
    print("-" * 62)
    for r in results:
        v1, v2 = r["v1"], r["v2"]
        dsim = v2["similarity"] - v1["similarity"]
        print(f"{r['id']:<6}{str(r['question_type']):<18}"
              f"{_fmt(v1['similarity']):>8}{_fmt(v2['similarity']):>8}{dsim:>+7.2f}"
              f"{_fmt(v2['root_cause_match']):>7}{_fmt(v2['evidence_coverage']):>8}")

    # Aggregate summary.
    print("\n=== Summary ===")
    print(f"Scenarios:                 {s['n_scenarios']}")
    print(f"Mean similarity  V1 -> V2: {_fmt(s['similarity_v1'])} -> {_fmt(s['similarity_v2'])}  "
          f"(improvement {s['improvement']:+.2f})")
    print(f"Mean root-cause  V2:       {_fmt(s['root_cause_v2'])}")
    print(f"Mean evidence coverage V2: {_fmt(s['coverage_v2'])}")
    if s["generalization_lift"] is not None:
        print(f"Generalization lift (warm V1 vs cold V1): {s['generalization_lift']:+.2f}")
    print(f"Avg latency V2:            {s['avg_latency_ms_v2']} ms")

    print("\n=== Success criteria ===")
    for name, met in s["targets_met"].items():
        print(f"  [{'PASS' if met else 'miss'}] {name}")

    print(f"\nResults saved to {config.STORES_DIR / 'history.json'}")
    print("Run the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
