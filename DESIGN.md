# Design & Architecture

## 1. Goal
Answer questions about a company's internal knowledge, show the reasoning, and get better after
a human expert corrects the answer. A question is investigated against synthetic sources to
produce a first answer (V1) with a reasoning trace. A human expert gives the correct answer. The
system runs gap analysis, writes a learning event, saves it, and a re-run (V2) is measurably
better. Learning is in-context and memory-backed; no fine-tuning (out of scope).

## 2. Constraints
Synthetic data only. Cross-platform (Linux and macOS). Reasoning history is kept. Targets:
similarity ≥0.75, root cause ≥0.70, evidence coverage ≥0.80, V1→V2 improvement ≥0.20, latency
<15s, scenario coverage 100%.

## 3. Stack
| Layer | Choice | Notes |
|---|---|---|
| LLM | Groq free tier (default), Ollama, or a deterministic stub | OpenAI-compatible HTTP, no SDK |
| Embeddings | `bge-small-en-v1.5`, numpy hashing fallback | local |
| Reranker | `bge-reranker-base` cross-encoder (optional) | local |
| Vector store | numpy cosine matrix | transparent, dependency-light |
| Knowledge graph | networkx | deterministic relations |
| Dashboard | Streamlit | optional |

The provider is swappable via `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL`. With no key the
engine falls back to the stub so the pipeline still runs. The same model answers both passes (the
70B by default). The smaller 8B model only classifies the question and writes the lesson, and the
70B also runs the judge.

## 4. Three stores
- RAG store (`vectorstore.py`): one self-contained chunk per natural unit (ticket, commit, Slack
  thread, wiki doc, incident, release) with metadata and a context prefix. Answers "what does the
  text say?"
- Knowledge graph (`kg.py`): typed entities (service, person, team, release, incident, ticket,
  commit) and relations (owns, blocks, caused/affects, in_release, depends_on). Answers "how is it
  connected?" deterministically, with no hallucination on relationships.
- Learning Memory (`memory.py`): saved lessons (vector-retrievable), KG overrides (factual
  corrections), and an exact-question answer memory. Answers "what did we learn from experts?"

## 5. Retrieval pipeline (`retrieve.py`)
1. Classify the question into a type (8B, `classify.py`) so lessons can transfer by type.
2. Entity match: string-match the question against the KG vocabulary.
3. Hybrid search: dense vector + BM25 keyword, plus KG multi-hop chunks (entities expanded 2 hops
   to their linked chunks). This surfaces buried evidence that isn't similar to the question text.
4. RRF fusion of the three ranked lists.
5. Cross-encoder rerank to the top `FINAL_K` evidence (skipped if the reranker isn't installed).
6. Learning Memory: (a) if this exact question was taught before, recall the expert's answer so
   the re-run reproduces it; (b) lessons matched by semantic, entity, type, or topic signal;
   same-subject (entity-matched) lessons also pull in the expert's recommended evidence.
7. Groundedness: `entities OR BM25-overlap OR dense≥0.35`. Below that it says "insufficient
   evidence" with low confidence. Stopwords are filtered so groundedness reflects real overlap.

## 6. Investigation (`investigate.py`)
Assembles context (evidence + KG facts + labeled lessons) and returns
`{answer, root_cause, reasoning_trace, cited_evidence_ids, confidence}`.
- Citation grounding: cited IDs are intersected with the retrieved set, so hallucinated citations
  are dropped.
- Confidence: a blend of retrieval groundedness and the model's own estimate.
- V1 vs V2: the same model answers both passes; only the retrieved context differs. V1 has no
  Learning Memory; V2 does, and a taught question's re-run reproduces the expert's saved answer
  (`use_lessons` gates the memory).
- The stub path mirrors this deterministically for offline runs.

## 7. Gap analysis and metrics (`judge.py`, `metrics.py`)
- Evidence coverage: deterministic set overlap of cited vs gold evidence IDs.
- Similarity and root-cause: an LLM judge blended 70/30 with embedding cosine (each clamped to
  [0,1]), or embedding heuristics in stub mode.
- Aggregated to mean V1/V2 similarity, improvement, root-cause, coverage, latency, and a
  generalization lift (warm V1 with prior lessons vs cold V1).

## 8. Learning (`learn.py`)
From the gap, write a generalized lesson keyed to the question type (not a memorized answer), and
route it:
- a strategy goes to the Learning Memory (with the expert's recommended evidence IDs and corrected
  root cause attached for same-subject reuse);
- a factual fix (ownership) goes to the knowledge graph as an override that supersedes stale docs.

The expert's answer is also stored in an exact-question answer memory, so a same-question re-run
reproduces it (the strong same-question gain), while different questions of the same type get only
the strategy lesson (the approach transfers, the answer does not leak).

Dedup/reinforce: a near-duplicate lesson of the same type and overlapping subject is reinforced
(counter++) instead of duplicated, which keeps the store clean.

## 9. Dataset design
`data/build_dataset.py` builds a small, consistent company with intentionally imperfect sources:
a false INC-9 postmortem ("load spike"), a misleading v2.1 release note ("QA backlog"), a stale
owner wiki, and a few noise services (search, billing) that act as distractors. The expert
answers also include things the docs don't have: resolutions, prevention steps, ETAs,
mitigations, escalation paths. So the first answer is often incomplete or misled, and the expert
correction genuinely helps. This makes the learning gap realistic rather than staged. The biggest
V1→V2 gains are on the false and stale questions (+13% to +23%).

## 10. Flow summary
```
build_dataset → ingest(vectors + graph)
question → retrieve → investigate → Answer V1
expert  → judge(gap) → learn(persist) → retrieve → investigate → Answer V2 → re-score
                                                                  → dashboard (trends)
```
