# Verification

Every check below was run on 2026-10-18 in the build environment, except those marked BLOCKED.
Raw output is in `docs/evidence/` (file numbers in the last column).

Status: **PASS** ran and succeeded · **FAIL→FIXED** ran, failed, fixed, re-run passed ·
**BLOCKED** could not run here (reason given).

## Environment

| Item | Value |
|---|---|
| Host | Ubuntu 24.04, Python 3.13.16, Docker 29.8.2 (BuildKit) |
| Container base used for local builds | `local/ubuntu-noble-python:3.12` — Ubuntu 24.04 minbase + Python 3.12.3, built with `debootstrap` |
| Kubernetes | k3s v1.33.5+k3s1, single node, with metrics-server and local-path provisioner |

Why not the defaults: this environment cannot reach Docker Hub or any container registry, so
`python:3.12-slim` could not be pulled and kind/minikube node images were unavailable. The
Dockerfile takes `BASE_IMAGE` as a build argument; local builds passed the debootstrap base, CI and
your laptop use the default `python:3.12-slim`. Three k3s workarounds were needed for this sandbox
only (none touch the repository): k3s's bundled runc 1.3.1 replaced by the host's runc 1.5.1;
containerd `restrict_oom_score_adj = true`; the node IP added to `NO_PROXY` so `kubectl logs` works.

## Results

| # | Check | Command | Status | Evidence |
|---|---|---|---|---|
| 1 | Unit tests (31: 25 original + 6 new) | `pytest -q` | PASS | 01, 05 |
| 2 | Lint, correctness rules | `ruff check .` | PASS | 05 |
| 3 | Behaviour unchanged by the DevOps work | offline `run_all.py` on `ac9abc8` vs `00239e4`, same stores | PASS — byte-identical score tables | 02 |
| 4 | Dataset regeneration deterministic | `python data/build_dataset.py` in a clean container, `diff -r data/` | PASS — identical to committed data | — |
| 5 | CI `test` job replayed in a clean Python 3.12 container | install pins → ruff → pytest → build stores → `engine.health` → `run_all.py` | FAIL→FIXED: plain `pytest` could not import `engine`; added `pythonpath = ["."]` in `pyproject.toml` | 05 |
| 6 | Image build | `docker build --build-arg BASE_IMAGE=local/ubuntu-noble-python:3.12 ...` | PASS (847 MB, 196 MB compressed) | 03 |
| 7 | Image build on `python:3.12-slim` | default `docker build .` | BLOCKED — Docker Hub unreachable | — |
| 8 | Dockerfile lint | `hadolint Dockerfile` | PASS (DL3006 ignored: ARG-based FROM) | — |
| 9 | Container smoke test, hardened run (`--read-only --cap-drop ALL --security-opt no-new-privileges`) | `scripts/smoke-test.sh reasoning-engine:0.1.0-dev` | PASS: liveness, readiness, UID 10001, read-only code, one question, dashboard renders | 04 |
| 10 | Docker HEALTHCHECK | `docker inspect -f '{{.State.Health.Status}}'` | PASS — `healthy` | — |
| 11 | No secret or proxy CA in image layers | inspect `/run/secrets`, `docker history` | PASS | — |
| 12 | Workflow syntax | `actionlint` | PASS | — |
| 13 | Manifest schema, base + persistent overlay | `kubectl kustomize ... \| kubeconform -strict -kubernetes-version 1.33.0` | PASS — 13 resources valid | — |
| 14 | CI policy checks, with a negative control | policy script from `ci.yml`; then a copy using `:latest` | PASS; negative control detected | — |
| 15 | Secret scan, full history / working tree / staged | `gitleaks git`, `gitleaks dir`, `gitleaks git --staged` | FAIL→FIXED: the README placeholder `GROQ_API_KEY='<key>'` (commit `7f4321b`) was flagged as `generic-api-key`; `.gitleaks.toml` allowlists `='<placeholder>'` lines only. Re-run: history and tree clean; negative control with a realistic `gsk_…` key still caught | 06 |
| 16 | Dependency CVEs | `pip-audit -r requirements-runtime.txt --strict` | PASS — none known | 06 |
| 17 | Image CVE scan | `trivy image --severity CRITICAL,HIGH` | BLOCKED — trivy DB download refused (mirror.gcr.io) | 06 |
| 18 | Deploy; PSA `restricted` admits the pod | `kubectl apply -k k8s/base`; `rollout status` | PASS | 07 |
| 19 | Pod hardening in the cluster | `id`, write to `/app`, SA token path | PASS — UID 10001, read-only FS, no token | 07 |
| 20 | Service reachable | `kubectl port-forward svc/reasoning-engine` + `/_stcore/health`, `GET /` | PASS — `ok`, 200 | — |
| 21 | NetworkPolicy enforced | TCP to API server and DNS from the pod, with and without the policy | PASS — API blocked with policy, reachable without; DNS works | 08 |
| 22 | Readiness probe takes a broken pod out of the Service | corrupt `vector_meta.json` in the pod, then restore | PASS — 0/1 Ready, endpoints empty, probe message names the file; recovered | 09 |
| 23 | Resource use vs requests/limits | `kubectl top pod` after an in-pod benchmark + dashboard render | PASS — 225m CPU, 50Mi memory (request 100m/192Mi, limit 1/512Mi) | 10 |
| 24 | Release 0.1.0-dev → 0.2.0-dev | `kubectl apply -k`; `scripts/verify-release.sh 0.2.0-dev` | PASS — surge pod seen, image, Ready, app version all 0.2.0-dev | 11 |
| 25 | Failed release (tag does not exist) | `kubectl set image ... :0.3.0-missing` | PASS — `ErrImagePull`, `ProgressDeadlineExceeded`, old pod kept serving 0.2.0-dev | 12 |
| 26 | Rollback with `rollout undo` | `kubectl rollout undo` | PASS | 12 |
| 27 | Rollback to a chosen revision | `rollout undo --to-revision=1`; `verify-release.sh 0.1.0-dev` | FAIL→FIXED: script counted the terminating old pod; fixed in `94bc2ed`, re-run PASS | 13 |
| 28 | Fixed script during termination; Git and cluster back in line | `kubectl apply -k k8s/base`; verify immediately | PASS | 14 |
| 29 | No downtime during release operations | in-namespace poller, Service health every 0.5 s | PASS — 0 failures across #25–#28; 22 failures only during the deliberate pod deletions / Recreate test (#30) | 17 |
| 30 | Learning memory: emptyDir vs PVC | teach one lesson, delete pod, count lessons | PASS — base loses it (1→0), persistent overlay keeps it (1→1) | 15 |
| 31 | Real UI requests through Service → pod → Streamlit | `scripts/ui-probe.py` (WebSocket client) ×4, incl. an unanswerable question | PASS — 3 grounded answers, 1 "insufficient evidence" | 16 |
| 32 | Runbook log queries | latency summary and fallback count from `kubectl logs` | PASS (first attempt used `kubectl exec`, which does not reach the main log; kept as 16a) | 16, 16a |
| 33 | GitHub-hosted CI and release workflows | push / tag | BLOCKED — requires pushing; not done by design | — |
| 34 | Groq LLM mode | `LLM_PROVIDER=groq` with a key | BLOCKED — no key and no egress to api.groq.com here; only stub mode was exercised | — |

## What this does not prove

- The image was not built on `python:3.12-slim`. The first CI run on GitHub is the first build on
  that base. If it fails, the likely spots are `groupadd`/`useradd` flags and the venv path.
- No answer was produced by the real LLM in any test. All answers above are from the offline stub.
- Load beyond one user was not tested. The 50Mi measurement is one quiet pod, not a sizing study.
