"""Streamlit dashboard: benchmark trends + a live Ask box with human-in-the-loop.

Run:  streamlit run app.py
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine import config, health, memory, metrics, store
import pipeline

# UI panels — flip any of these to True to show that panel again in the Ask tab.
# (Frontend-only; the backend always computes them.)
SHOW_CONFIDENCE = True    # confidence score in the answer header
SHOW_EVIDENCE = True     # "Evidence used" table
SHOW_KG_FACTS = True      # "Knowledge-graph facts" panel
SHOW_LESSONS = True       # "Lessons applied" + the learned-lesson detail on teach


def _scenarios():
    try:
        return json.loads(config.SCENARIOS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _example_questions():
    return [s["question"] for s in _scenarios()]


def _scenario_answers():
    """Map each saved question -> its stored expert (gold) answer."""
    return {s["question"]: s.get("gold_answer", "") for s in _scenarios()}

st.set_page_config(page_title="Organizational Reasoning Engine", layout="wide")
st.title("Expert-Learning Organizational Reasoning Engine")
st.caption(f"LLM provider: **{config.LLM_PROVIDER}**"
           + ("  · running offline (stub heuristics, no key)" if config.USE_STUB else "")
           + f"  · version `{config.APP_VERSION}` (`{config.GIT_SHA[:7]}`)")

_health = health.check()
if not _health["ready"]:
    st.error("Not ready: " + "; ".join(_health["problems"])
             + ". Build the stores first (`python -m ingest.build_vectors` and "
               "`python -m ingest.build_graph`).")
    st.stop()

tab_ask, tab_bench, tab_lessons = st.tabs(["💬 Ask", "📊 Benchmark", "🧠 Learning Memory"])


# --------------------------------------------------------------------------- Ask
with tab_ask:
    st.subheader("Ask any question")
    st.write("Type your own question or pick an example. The engine investigates the "
             "knowledge sources (+ everything it has learned) and shows its answer and "
             "reasoning. Then provide the expert answer to teach it live.")
    if config.USE_STUB:
        st.info("Offline mode (no API key): answers are composed by deterministic heuristics "
                "and similarity is scored with embeddings. Add a free Groq key in `.env` "
                "(`LLM_PROVIDER=groq`) for full LLM-written answers and an LLM judge.")

    with st.form("ask_form"):
        example = st.selectbox("Pick an example question…",
                               ["— type my own below —"] + _example_questions())
        typed = st.text_input("…or type any question",
                              placeholder="e.g. What is blocking the v2.2 milestone?")
        submitted = st.form_submit_button("🔎 Investigate", type="primary")

    if submitted:
        question = typed.strip() or ("" if example.startswith("—") else example)
        if question:
            st.session_state["ask_answer"] = pipeline.ask(question)
            st.session_state["ask_q"] = question
            st.session_state.pop("taught", None)
        else:
            st.warning("Type a question or pick an example, then click Investigate.")

    ans = st.session_state.get("ask_answer")
    if ans:
        grounded = ans["grounded"]
        header = "### Answer (V1)"
        if SHOW_CONFIDENCE:
            header += f" — confidence `{ans['confidence']:.2f}`"
        if not grounded:
            header += "  ⚠️ insufficient evidence"
        st.markdown(header)
        st.caption(f"Question: {st.session_state.get('ask_q', '')}")
        st.write(ans["answer"])
        if ans.get("root_cause"):
            st.markdown(f"**Root cause:** {ans['root_cause']}")

        # Reasoning trace — always shown.
        with st.expander("🧭 Reasoning trace", expanded=True):
            for step in ans["reasoning_trace"]:
                st.write("- " + step)

        if SHOW_EVIDENCE:
            # Only the sources the answer actually cited (relevant), not all retrieved.
            cited_ids = ans.get("cited_evidence_ids", [])
            ev = [e for e in ans.get("evidence", []) if e["source_id"] in cited_ids]
            st.markdown("**Evidence used** (only the sources the answer relied on):")
            if ev:
                st.dataframe(pd.DataFrame([{
                    "source": e["source_id"], "type": e["source_type"], "snippet": e["snippet"],
                } for e in ev]), use_container_width=True, hide_index=True)
            else:
                st.write("(the answer did not cite specific sources)")

        if SHOW_KG_FACTS:
            with st.expander("🔗 Knowledge-graph facts"):
                for f in ans["kg_facts"] or ["(none)"]:
                    st.write("- " + f)

        if SHOW_LESSONS:
            with st.expander("🧠 Lessons applied"):
                st.write(ans["lessons_used"] or "(none yet)")

        st.divider()
        st.markdown("#### Teach the engine (human-in-the-loop)")
        # For a saved question (picked from the dropdown) the stored expert answer is
        # auto-filled; for a typed question the box starts empty. Editable either way.
        asked_q = st.session_state.get("ask_q", "")
        saved_answer = _scenario_answers().get(asked_q, "")
        if saved_answer:
            st.caption("This question has a saved expert answer — it's pre-filled below. "
                       "Edit it if you like, then submit to learn and re-run.")
        else:
            st.caption("Provide the correct/expert answer, then submit to learn and re-run.")
        with st.form("teach_form"):
            expert = st.text_area("Expert (ground-truth) answer", value=saved_answer,
                                  key=f"expert::{asked_q}", height=150)
            taught_submit = st.form_submit_button("📚 Submit expert answer → learn → re-run")
        if taught_submit and expert.strip():
            st.session_state["taught"] = pipeline.teach(asked_q, expert.strip(), ans)

        taught = st.session_state.get("taught")
        if taught:
            gap = taught["gap_v1"]   # how the 1st answer compared to the expert answer

            # ---- 1) Gap analysis: what the first answer missed ----
            st.markdown("### 🔍 Gap analysis — what the 1st answer missed")
            g1, g2 = st.columns(2)
            g1.metric("1st-answer accuracy", f"{gap['similarity'] * 100:.0f}%")
            g2.metric("Evidence coverage", f"{gap['evidence_coverage'] * 100:.0f}%",
                      help="Share of the sources the expert used that the 1st answer cited.")
            missing = gap.get("missing_evidence_ids") or []
            if missing:
                st.markdown(f"**Sources the expert used that V1 did not cite:** `{', '.join(missing)}`")
            else:
                st.caption("V1 cited all of the expert's sources.")
            if gap.get("missing_reasoning"):
                st.markdown("**Reasoning / points V1 missed:**")
                for m in gap["missing_reasoning"]:
                    st.write("- " + str(m))
            if gap.get("factual_errors"):
                st.markdown("**Factual errors in V1:**")
                for e in gap["factual_errors"]:
                    st.write("- " + str(e))
            if gap.get("narrative_diff"):
                st.caption("Summary of the difference: " + str(gap["narrative_diff"]))

            # ---- 2) Learning event ----
            if SHOW_LESSONS:
                le = taught["learned"]
                st.success(f"Learning event **{le['action']}** ({le['lesson']['type']}): "
                           f"{le['lesson']['lesson_text']}")
            else:
                st.success("Captured the gap as a learning event and re-ran.")

            # ---- 3) Improved V2 answer ----
            st.markdown("### ✅ Answer (V2 — after learning)")
            st.write(taught["answer_v2"]["answer"])

            # ---- 4) Measurable improvement (V1 vs V2 vs your expert answer) ----
            acc1 = taught["gap_v1"]["similarity"] * 100
            acc2 = taught["gap_v2"]["similarity"] * 100
            st.markdown("**Accuracy vs your expert answer**")
            cA, cB, cC = st.columns(3)
            cA.metric("1st answer (V1)", f"{acc1:.0f}%")
            cB.metric("2nd answer (V2)", f"{acc2:.0f}%", f"{acc2 - acc1:+.0f}%")
            cC.metric("Improvement", f"{acc2 - acc1:+.0f}%")
            st.caption("Accuracy = how close each AI answer is to your expert answer — scored by "
                       "the LLM judge blended with embedding cosine (0–100%).")


# ---------------------------------------------------------------------- Benchmark
with tab_bench:
    st.subheader("Benchmark — does learning improve accuracy across many questions?")
    st.caption(
        "Runs the 10 built-in **complex, multi-source** test questions (where the expert's correct "
        "answer is already known). "
        "For each question the engine **(1)** answers cold = **V1**, **(2)** is shown the expert "
        "answer and learns from it, **(3)** answers again = **V2**. Every number below is the "
        "**accuracy** of an AI answer — how close it is to the expert answer (0–100%). The point: "
        "see whether **V2 (after learning) beats V1 (before)**.")
    if st.button("Run full benchmark", type="primary"):
        with st.spinner("Running scenarios…"):
            st.session_state["bench"] = pipeline.run_benchmark(reset=True)

    bench = st.session_state.get("bench")
    if not bench and store.load_benchmark():
        results = store.load_benchmark()
        bench = {"results": results, "summary": metrics.aggregate(results)}

    if bench:
        results, s = bench["results"], bench["summary"]
        rows = [{
            "question": r["id"], "topic": r["question_type"],
            "V1 accuracy %": round(r["v1"]["similarity"] * 100),
            "V2 accuracy %": round(r["v2"]["similarity"] * 100),
            "improvement %": round((r["v2"]["similarity"] - r["v1"]["similarity"]) * 100),
            "coverage %": round(r["v2"]["evidence_coverage"] * 100),
        } for r in results]
        df = pd.DataFrame(rows).set_index("question")

        m1, m2, m3 = st.columns(3)
        m1.metric("Avg 1st-answer accuracy (V1)", f"{s['similarity_v1'] * 100:.0f}%")
        m2.metric("Avg 2nd-answer accuracy (V2)", f"{s['similarity_v2'] * 100:.0f}%",
                  f"{s['improvement'] * 100:+.0f}% after learning")
        m3.metric("Avg evidence coverage (V2)", f"{s['coverage_v2'] * 100:.0f}%")

        st.markdown("**Per-question accuracy — 1st answer (V1) vs after learning (V2)**")
        st.dataframe(df, use_container_width=True)

        st.markdown("### Success criteria (from the project brief)")
        crit = pd.DataFrame([{
            "metric": c["metric"], "target": c["target"], "achieved": c["achieved"],
            "status": "✅ met" if c["met"] else "❌ miss",
        } for c in s["criteria"]]).set_index("metric")
        st.table(crit)
    else:
        st.info("No benchmark run yet. Click **Run full benchmark** (or run `python run_all.py`).")


# ----------------------------------------------------------------- Learning Memory
with tab_lessons:
    st.subheader("Learning Memory")
    lessons = memory.load_lessons()
    overrides = memory.load_overrides()
    st.markdown(f"**{len(lessons)} lessons · {len(overrides)} knowledge-graph overrides**")
    if lessons:
        st.dataframe(pd.DataFrame([{
            "id": l["lesson_id"], "type": l["type"],
            "question_type": l.get("trigger", {}).get("question_type"),
            "reinforced": l.get("reinforced_count", 1),
            "lesson": l["lesson_text"],
        } for l in lessons]).set_index("id"), use_container_width=True)
    if overrides:
        st.markdown("**Authoritative corrections (KG overrides)**")
        for o in overrides:
            st.write(f"- {o['fact_text']}  _(entities: {', '.join(o['entities'])})_")
    if not lessons and not overrides:
        st.info("Nothing learned yet — run the benchmark or teach the engine in the Ask tab.")
