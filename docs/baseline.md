# Baseline — state before the DevOps work

This file records the project exactly as it was received, before any change on the
`devops-improvements` branch. Nothing here describes work added later.

## Identity

| Item | Value |
|---|---|
| Project | Final_Project-Bazinga- — Expert-Learning Organizational Reasoning Engine (self-improving RAG) |
| Purpose | Answers questions about a company's internal knowledge (Slack, tickets, wiki, commits, incidents, releases), shows its reasoning, takes an expert correction, stores a lesson, and answers better on the re-run |
| Upstream baseline commit | `2ffe22a857d4a5637c5d247518773280722ae9e9` |
| Upstream branch | `main` |
| Upstream repository | GitHub repository `Final_Project-Bazinga-` (owner not recorded in the received files) |
| Permanent URL | `https://github.com/<owner>/Final_Project-Bazinga-/commit/2ffe22a857d4a5637c5d247518773280722ae9e9` — replace `<owner>` |
| Local import commit | `ac9abc84e541532176e0e04a3c82de5672dc2751` on local `main` |

### How the baseline hash was established

The project arrived as GitHub's "Download ZIP" archive (`Final_Project-Bazinga--main.zip`).
GitHub writes the source commit SHA into the ZIP comment; `unzip -l` on the archive prints
`2ffe22a857d4a5637c5d247518773280722ae9e9`. That is the upstream baseline.

A GitHub ZIP does not contain `.git`, so the upstream history before `2ffe22a` is not in
this repository. The archive contents were committed locally as one snapshot commit,
`ac9abc8` ("chore: import upstream baseline snapshot (GitHub commit 2ffe22a)"),
created 2026-10-18 11:48:58 UTC, before any DevOps change.

Verification performed: the 67 files tracked in `ac9abc8` were compared with the extracted
ZIP using `diff -r`; they are byte-identical. `ac9abc8` therefore has the same file tree as
upstream `2ffe22a`, but a different commit hash and no shared ancestry with it.
`docs/transfer-to-another-laptop.md` explains how to replay the DevOps commits on top of
the real upstream commit before opening the pull request.

## Application

| Aspect | Baseline state |
|---|---|
| Language | Python 3 (tested here on 3.13.16) |
| UI | Streamlit dashboard, `app.py`, default port 8501 |
| CLI | `run_all.py` (benchmark), `run_scenario.py` (single question) |
| Core | `engine/` — retrieval (BM25 + vectors + RRF + rerank + knowledge graph), investigation, judge, learning memory |
| Ingest | `data/build_dataset.py` → `data/sources/`, `ingest/build_vectors.py`, `ingest/build_graph.py` → `stores/` |
| LLM | Groq over plain HTTP (`urllib`), Ollama, or `stub` (offline heuristics). With no `GROQ_API_KEY` the engine falls back to `stub` |
| Embeddings | `sentence-transformers` bge-small, or a numpy hashing fallback (`EMBEDDING_MODEL=hashing`) |
| State | JSON/NPZ files in `stores/` (vector store, graph, lessons, KG overrides, answer memory, history, ask log). Gitignored |
| Dependencies | `requirements.txt`, lower bounds only (`>=`), no lock or pins |
| Tests | 25 pytest tests in `tests/`, forced offline (hashing embedder + stub LLM). `pytest -q` → 25 passed |

## Deployment and DevOps features that already existed

- Deployment method: local only. `setup.sh` creates `.venv`, installs dependencies (CPU-only
  torch on Linux), builds the dataset and stores, copies `.env.example` to `.env`. The app is
  started by hand with `streamlit run app.py`.
- Containers: none. No Dockerfile, no `.dockerignore`, no compose file.
- Kubernetes: none.
- CI/CD: none. No `.github/workflows`, no pipeline of any kind.
- Release control: none. No version number, no tags, no changelog.
- Observability: `print()` messages; per-answer `latency_ms` recorded inside the answer record;
  benchmark history written to `stores/history.json`; live teach events to `stores/ask_log.json`.
  No structured logs, no health endpoint of the app's own (Streamlit's built-in
  `/_stcore/health` exists but was not used or documented).
- Security: `.env` gitignored; `.env.example` with an empty `GROQ_API_KEY`; key read from the
  environment. No secret scanning, dependency audit, or container hardening.
- Configuration: environment variables / `.env` loaded by a small parser in `engine/config.py`.

## Known limitations at baseline

1. No reproducible build: unpinned dependencies; the default install pulls torch.
2. `stores/` path fixed to `<repo>/stores`; cannot point state at a separate writable volume.
3. No way to tell from a running instance which version it is.
4. No readiness signal that the stores were built; the app starts and fails on first question.
5. Learning state is local files: one process, one disk. Not shareable between instances.
6. Large binaries tracked in Git (three `.pptx`, `ONE_PAGER.pdf`, `for_signing.docx`, PNG screenshots, ~8 MB).
7. Four pyflakes findings (unused imports/variables) in the baseline code.
