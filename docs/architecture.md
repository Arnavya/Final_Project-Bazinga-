# Architecture and operation

Application internals (retrieval, learning loop) are described in `DESIGN.md`. This file covers
what an operator needs: processes, ports, data, configuration, dependencies, failure boundaries.

## Runtime shape

One Python process: Streamlit serving `app.py` on port 8501. There is no separate API server and
no database. Everything the app reads or writes is a file under the state directory (`stores/`).

```
browser ──HTTP/WebSocket :8501──▶ Streamlit (app.py)
                                     │
                                     ├─ pipeline.ask / teach / run_benchmark
                                     │     ├─ engine.retrieve   ── reads stores/vector_store.npz, vector_meta.json, graph.json
                                     │     │                    ── reads lessons.json, kg_overrides.json, question_answers.json
                                     │     ├─ engine.investigate ─▶ LLM (HTTPS to Groq) or stub (no network)
                                     │     ├─ engine.judge / learn ─▶ writes lessons.json, kg_overrides.json, question_answers.json
                                     │     └─ engine.store      ── writes history.json, ask_log.json
                                     └─ reads data/scenarios.json (example questions + gold answers)
```

## Request flow (Ask tab)

1. User submits a question → Streamlit reruns the script for that session.
2. `pipeline.ask` → `investigate.investigate(question, use_lessons=True)`.
3. `retrieve` classifies the question, matches knowledge-graph entities, runs BM25 + vector
   search + KG expansion, fuses with RRF, optionally reranks, adds matching lessons.
4. If the evidence is too weak the answer is "insufficient evidence" with low confidence.
5. Otherwise the LLM (or stub) produces answer, root cause, trace, citations, confidence.
   Citations not in the retrieved set are dropped.
6. Teach: expert answer → `judge` (gap analysis) → `learn` (lesson + override + answer memory,
   persisted) → V2 re-run.

## Ports

| Port | Protocol | Purpose |
|---|---|---|
| 8501 | HTTP + WebSocket | Streamlit UI; `/_stcore/health` returns `ok` when the server is up |

## Data

| Path | Built by | Written at runtime | Notes |
|---|---|---|---|
| `data/sources/` | `data/build_dataset.py` (deterministic) | no | synthetic Slack, tickets, wiki, commits, incidents, releases |
| `data/scenarios.json` | `data/build_dataset.py` | no | 10 gold scenarios |
| `stores/vector_store.npz`, `vector_meta.json` | `ingest.build_vectors` | no | must match the embedder in use |
| `stores/graph.json` | `ingest.build_graph` | no | |
| `stores/lessons.json`, `kg_overrides.json`, `question_answers.json` | learning loop | yes | the "Learning Memory" |
| `stores/history.json`, `ask_log.json` | benchmark / teach | yes | reasoning history |

The vector store and the query embedder must use the same embedding model. Stores built with
`EMBEDDING_MODEL=hashing` (512-dim) cannot be queried with bge-small (384-dim) and vice versa.

## Configuration

All configuration is environment variables (a `.env` file is read if present and never
overrides the real environment). See `.env.example`.

| Variable | Default | Effect |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq`, `ollama`, or `stub` |
| `GROQ_API_KEY` | empty | secret; when empty with `groq`, the engine runs as `stub` |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_SMALL_MODEL`, `LLM_TIMEOUT` | Groq values | LLM endpoint |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | `hashing` forces the dependency-free embedder |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | skipped if sentence-transformers is absent |

## External dependencies

| Dependency | Needed when | Failure effect |
|---|---|---|
| Groq API (HTTPS) | `LLM_PROVIDER=groq` with a key | `llm.chat` retries 429/5xx and network errors 3× with backoff, then raises `LLMError`; `investigate`, `judge`, `learn` and `classify` catch it and fall back to the deterministic stub for that call. Answers degrade silently instead of failing |
| Ollama | `LLM_PROVIDER=ollama` | same as above |
| Hugging Face model download | first use of bge models | falls back to hashing embedder and no reranker |

## Failure boundaries

- Stores missing or unreadable: every question fails. Detectable before traffic (readiness).
- LLM unreachable: requests still return, built by the stub fallback, with lower quality. The
  process stays healthy, so health checks do not catch this; it must be seen in logs.
  `stub` mode has no external dependency at all.
- Corrupt `lessons.json` etc.: learning features fail; deleting the file resets memory.
- Concurrency: two processes writing the same `stores/` can lose updates (read-modify-write of
  whole JSON files, no locking). Run one writer per state directory.
