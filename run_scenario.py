"""Run a single question end-to-end and print the V1 -> learning -> V2 story.

Usage:
    python run_scenario.py                 # runs the first gold scenario
    python run_scenario.py Q-02            # runs a specific gold scenario by id
    python run_scenario.py "Why was v2.1 delayed?"   # an ad-hoc question (no scoring)
"""
from __future__ import annotations

import sys

from engine import investigate, memory
from pipeline import load_scenarios, run_one


def _print_answer(title: str, a: dict) -> None:
    print(f"\n--- {title} (confidence {a['confidence']:.2f}, {a['latency_ms']} ms) ---")
    print(f"Answer: {a['answer']}")
    if a.get("root_cause"):
        print(f"Root cause: {a['root_cause']}")
    print(f"Cited: {a['cited_evidence_ids']}")
    print("Reasoning trace:")
    for step in a["reasoning_trace"]:
        print(f"  - {step}")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    scenarios = load_scenarios()
    by_id = {s["id"]: s for s in scenarios}

    if arg is None:
        scenario = scenarios[0]
    elif arg in by_id:
        scenario = by_id[arg]
    else:
        # Ad-hoc free-form question: no ground truth, so just show the answer.
        print(f"Ad-hoc question (no gold answer): {arg!r}")
        a = investigate.investigate(arg, version="V1", use_lessons=True)
        _print_answer("AI answer", a)
        if not a["grounded"]:
            print("\n(Graceful fallback: insufficient evidence in the corpus.)")
        return

    memory.reset()
    print(f"Scenario {scenario['id']}: {scenario['question']}")
    print(f"Expert (ground-truth) answer: {scenario['gold_answer']}")

    r = run_one(scenario)
    _print_answer("Version 1 (no Learning Memory)", r["answer_v1"])
    print(f"\n[Gap] similarity={r['v1']['similarity']:.2f} "
          f"root_cause={r['v1']['root_cause_match']} "
          f"coverage={r['v1']['evidence_coverage']:.2f} "
          f"missing_evidence={r['v1']['missing_evidence_ids']}")

    le = r["learned"]
    print(f"\n[Learning event {le['action']}] {le['lesson']['lesson_id']} "
          f"({le['lesson']['type']}): {le['lesson']['lesson_text']}")

    _print_answer("Version 2 (after learning)", r["answer_v2"])
    print(f"\n[Gap] similarity={r['v2']['similarity']:.2f} "
          f"root_cause={r['v2']['root_cause_match']} "
          f"coverage={r['v2']['evidence_coverage']:.2f}")
    print(f"\nImprovement V1 -> V2: {r['v2']['similarity'] - r['v1']['similarity']:+.2f} similarity")


if __name__ == "__main__":
    main()
