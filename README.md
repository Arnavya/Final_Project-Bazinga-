# Self-Improving RAG — Expert-Learning Organizational Reasoning Engine

An AI that answers questions about a company's internal knowledge (Slack, tickets, wiki,
commits), shows its reasoning, and gets corrected by a human expert. It saves what it got
wrong and answers better the next time, including on questions it hasn't seen before.

---

## Quick start (Groq + local embeddings)

```bash
bash setup.sh                          # venv + deps + dataset + stores + .env
source .venv/bin/activate              # activate the venv setup.sh created
# edit .env and paste your free GROQ_API_KEY (from console.groq.com); LLM_PROVIDER=groq is the default
python run_all.py                      # benchmark: V1 -> learn -> V2 across the 10 questions
streamlit run app.py                   # open the dashboard
```

`setup.sh` installs everything in `requirements.txt`. The Groq LLM is called over plain HTTP
(no SDK), and `sentence-transformers` gives local `bge-small` embeddings plus a
`bge-reranker-base` cross-encoder. A free Groq key takes about a minute to make.

On Linux, `setup.sh` installs a CPU-only PyTorch so it doesn't download the large NVIDIA CUDA
packages (~2-3 GB). If you have an NVIDIA GPU and want the CUDA build, run `GPU=1 bash setup.sh`.

### No API key? Run it fully offline

Set `LLM_PROVIDER=stub` in `.env` (or `export LLM_PROVIDER=stub`) and the whole pipeline runs
with deterministic heuristics — no key, no model download, no network. Good for a quick look or CI.

### Manual setup (if you'd rather not use `setup.sh`)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/build_dataset.py           # synthetic sources + gold scenarios
python -m ingest.build_vectors         # RAG vector store
python -m ingest.build_graph           # knowledge graph
cp .env.example .env                    # then paste your GROQ_API_KEY (or set LLM_PROVIDER=stub)
```

### Tests

```bash
pytest -q                               # unit tests for the retrieval / scoring logic
```

The tests force the offline backends (hashing embedder + stub LLM), so they need no key,
no downloads, and no built stores.

---

## Prerequisites

| Use | Needs |
|---|---|
| Local run | Python 3.12 or 3.13 (both tested), `bash` |
| Container | Docker 23+ with BuildKit |
| Kubernetes | any cluster ≥ 1.27 with NetworkPolicy support (k3s, kind, minikube, managed); `kubectl` with built-in kustomize |
| Optional | metrics-server for `kubectl top`; a default StorageClass for the persistent overlay |

## Run in a container

```bash
docker build -t reasoning-engine:dev \
  --build-arg APP_VERSION=dev --build-arg GIT_SHA=$(git rev-parse HEAD) .
docker run --rm -p 8501:8501 reasoning-engine:dev                         # offline stub mode
docker run --rm -p 8501:8501 -e GROQ_API_KEY=... reasoning-engine:dev     # Groq LLM
scripts/smoke-test.sh reasoning-engine:dev                                # hardened smoke test
```

The image installs exact pins from `requirements-runtime.txt` (no torch), builds the dataset and
stores at build time with the hashing embedder, runs as UID 10001, and has a HEALTHCHECK on
Streamlit's `/_stcore/health`. Learned state goes to `STORES_DIR` (`/app/stores`).
`python -m engine.health` prints readiness as JSON and exits 1 if the stores are missing or broken.

## Deploy to Kubernetes

```bash
# load the image into a local cluster (or set newName to your registry in k8s/base/kustomization.yaml)
kind load docker-image reasoning-engine:<tag>          # or: docker save ... | sudo k3s ctr images import -
# set newTag in k8s/base/kustomization.yaml to <tag>, then:
kubectl apply -k k8s/base                              # emptyDir state
kubectl apply -k k8s/overlays/persistent               # or: lessons kept on a PVC
kubectl -n reasoning-engine rollout status deploy/reasoning-engine
kubectl -n reasoning-engine port-forward svc/reasoning-engine 8501:80   # open http://localhost:8501
```

Optional Groq key (never committed):

```bash
kubectl -n reasoning-engine create secret generic reasoning-engine-secrets --from-literal=GROQ_API_KEY='<key>'
kubectl -n reasoning-engine rollout restart deploy/reasoning-engine
```

What is deployed: namespace with Pod Security `restricted`, ServiceAccount without a token,
ConfigMap, Deployment (1 replica, RollingUpdate surge 1 / unavailable 0, startup + liveness on
`/_stcore/health`, readiness on `python -m engine.health`, requests 100m/192Mi, limits 1 CPU/512Mi,
non-root, read-only root FS, no capabilities, seccomp), ClusterIP Service, NetworkPolicy.

## CI/CD

`.github/workflows/ci.yml` runs on every pull request and push to `main`:
ruff + pytest + store build + readiness + offline benchmark; gitleaks over full history + pip-audit;
kustomize render + kubeconform + policy checks; hadolint + image build + smoke test + trivy.
`.github/workflows/release.yml` runs on `v*.*.*` tags and pushes
`ghcr.io/<owner>/reasoning-engine:<version>`. Deploying a release is a reviewed change to
`newTag` in `k8s/base/kustomization.yaml`.

## Release and rollback

```bash
scripts/verify-release.sh <version>                                     # rollout, image tag, Ready, app version
kubectl -n reasoning-engine rollout history deploy/reasoning-engine
kubectl -n reasoning-engine rollout undo deploy/reasoning-engine [--to-revision=N]
```

Full procedure, log events and troubleshooting: `docs/operations.md`.

## Security

Secrets never in Git or images; non-root read-only container; restricted pod security; no API
token; NetworkPolicy; exact dependency pins with pip-audit; SHA-pinned Actions; Dependabot.
Details and known gaps: `docs/security.md`.

## Logs and troubleshooting

`LOG_FORMAT=json` (default in the image) writes one JSON event per line to stdout:
`ask.completed` (latency, grounded, confidence), `teach.completed`, `llm.fallback_to_stub`, etc.
Question text is never logged. `kubectl -n reasoning-engine logs deploy/reasoning-engine`.
Symptom → cause table: `docs/operations.md` §5.

## Verification

34 checks, run locally on Docker and k3s, with raw output: `docs/verification.md`, `docs/evidence/`.
Not verified here: build on the `python:3.12-slim` base (Docker Hub blocked), trivy, the GitHub-hosted
workflow runs, and the Groq LLM path.

## Known limitations

- One replica. Lessons are JSON files written by one process; two pods would diverge or overwrite.
- Base deployment keeps lessons in `emptyDir`: lost when the pod is replaced. The persistent overlay fixes that but uses `Recreate`, so releases have a short outage.
- No authentication in front of the dashboard.
- No metrics endpoint; observability is logs plus `kubectl top`.
- Container image uses the hashing embedder (no torch), which is weaker than bge-small.

More: `docs/architecture.md`, `docs/decisions.md`, `docs/baseline.md`.

---

## What you'll see

`run_all.py` runs each question through V1 (no learning), captures the expert answer, creates
a learning event, and re-runs it as V2. It prints a scorecard:

```
ID    type                sim V1  sim V2   Δsim  rc V2  cov V2
--------------------------------------------------------------
Q-01  incident_rca          0.74    0.90  +0.16   1.00    1.00
Q-08  release_delay         0.66    0.89  +0.23   0.90    1.00
...
Mean similarity  V1 -> V2: 0.79 -> 0.88  (improvement +0.09)
```

`run_scenario.py Q-01` shows the full story for one question. `run_scenario.py "your question"`
answers an ad-hoc question, and declines if there is no evidence for it.

The dashboard (`streamlit run app.py`) has three tabs:
- Ask: pick a saved question (its expert answer auto-fills) or type your own. You see the
  answer and reasoning trace, submit the expert answer, then see the gap analysis (what V1
  missed) and the improved V2 with the accuracy change.
- Benchmark: run all 10 questions and see the per-question V1-vs-V2 table, the averages, and
  the 6 success criteria with pass/fail.
- Learning Memory: browse the lessons and corrections it has stored.

---

## How the learning works (no fine-tuning)

The model's weights never change. Learning is in-context, backed by memory:
1. Gap analysis compares the AI answer to the expert answer.
2. A learning event is created and saved. A reusable strategy goes to the Learning Memory (a
   vector index of lessons); a factual correction goes to the knowledge graph as an override.
3. On later questions, retrieval also searches the Learning Memory, so relevant lessons come
   back into context. Recalling them is what "memory" means here.

Re-running the same question (V1 to V2) is how we measure the gain. Lessons that help
*different* questions of the same type are the bigger win.

---

## Architecture (see `DESIGN.md` for detail)

```
sources ─ingest─▶ Vector store (RAG) + Knowledge graph + Learning Memory
question ─▶ retrieve (hybrid BM25+vector ─RRF─ rerank + KG multi-hop + lessons)
         ─▶ investigate ─▶ Answer (trace, citations, confidence)
expert   ─▶ judge (gap analysis) ─▶ learn (distill + route + persist)
re-run   ─▶ Answer V2 ─▶ re-score ─▶ dashboard
```

Accuracy comes from: semantic chunking with metadata, hybrid search (vector + BM25) fused with
RRF, cross-encoder reranking, knowledge-graph multi-hop retrieval, citation checking (cited IDs
must be in the retrieved set), confidence with a graceful "insufficient evidence" path, and
de-duplicated lessons.

---

## Project layout
```
data/build_dataset.py     synthetic sources + gold scenarios (deterministic)
ingest/                   chunker, build_vectors, build_graph
engine/
  config.py               paths, settings, retrieval params, targets
  embeddings.py           bge-small  (numpy hashing fallback)
  vectorstore.py          numpy cosine vector store
  kg.py                   graph load, entity match, traversal, facts
  rerank.py               bge-reranker cross-encoder (optional)
  classify.py             question-type classifier (routes lessons by type)
  retrieve.py             hybrid + RRF + KG + rerank + lessons + answer memory
  investigate.py          AI answer (same model both passes; stub fallback)
  judge.py                gap analysis / metrics per scenario
  learn.py                learning-event creation + routing
  memory.py               Learning Memory + KG overrides
  metrics.py              aggregate success metrics
  store.py                persist reasoning history
pipeline.py               orchestration (benchmark + live ask/teach)
run_all.py / run_scenario.py   CLI
app.py                    Streamlit dashboard
tests/                    pytest unit tests (retrieval, scoring, metrics, ops; offline)
setup.sh                  one-shot: venv + deps + dataset + stores + .env
engine/health.py          readiness check (python -m engine.health)
engine/logs.py            structured stdout logging
Dockerfile, docker/       container image and entrypoint
requirements-runtime.txt  exact pins for the image
k8s/base/                 Kubernetes manifests (kustomize)
k8s/overlays/persistent/  PVC-backed learning memory
.github/workflows/        CI and tag-driven release
scripts/                  smoke-test, verify-release, ui-probe
docs/                     baseline, architecture, decisions, operations, security, verification
```

---

## Results

Across 10 complex, multi-source questions (Groq + local embeddings), five of six success
criteria pass:

| Success metric | Target | Result |
|---|---|---|
| AI answer similarity to expert (V2) | ≥ 75% | **88%** ✅ |
| Root-cause identification (V2) | ≥ 70% | **94%** ✅ |
| Evidence coverage (V2) | ≥ 80% | **95%** ✅ |
| Response time | < 15 s | **~3.6 s** ✅ |
| Test-scenario coverage | 100% | **10/10** ✅ |
| Learning improvement (V1 → V2) | ≥ 20% | +9% (V1 79% → V2 88%) ⚠️ |

The learning signal is clearest where the sources actively mislead the first answer:
**+13% to +23%** on the false-postmortem ("load spike") and stale-owner-wiki questions.

The average improvement is +9% (under the 20% target) for an honest reason: the *same* model
answers both passes, so the cold first answer is already fairly strong (~79%), which caps the
headline delta. The mechanism the brief cares about — a correction on one question transferring
to *new* same-type questions — is the real win, and it shows up as the per-question lift above.

The data is intentionally messy. There is a wrong INC-9 postmortem that blames a "load spike",
a v2.1 release note that blames a "QA backlog", a stale owner wiki, and a few unrelated noise
services. So the first answer is often incomplete or wrong, and the expert correction actually
helps.

The same model answers both passes; only the retrieved context changes. An answer memory keyed
to the exact question makes the same-question V2 match the expert, while type-tagged strategy
lessons carry the approach to new questions. The smaller model is only used to classify the
question and write the lesson.

All data is synthetic. `stores/` is rebuilt by the ingest step and is gitignored.
