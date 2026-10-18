# Viva preparation

Answers are about this project only. "Done" = implemented and tested; "Not done" = future work.

## Architecture and request flow
One Python process: Streamlit on 8501. Browser opens a WebSocket; each click reruns `app.py` for
that session. Ask → `pipeline.ask` → `retrieve` (BM25 + vectors + knowledge graph + lessons, fused
with RRF) → `investigate` (Groq LLM, or stub if no key / on error) → answer with citations and
confidence. Teach → `judge` compares with the expert answer → `learn` writes a lesson and an answer
memory to `stores/` → V2 re-run. No database; all state is files in `STORES_DIR`.

## Baseline vs now
Baseline (`2ffe22a`): run by hand with `setup.sh` + `streamlit run`. No Docker, no Kubernetes,
no CI, no version, no health check, unpinned deps. 25 tests.
Now: readiness check, JSON logs, version in UI/health/logs; pinned non-root image; Kubernetes
manifests with probes, limits, hardening, NetworkPolicy; CI with tests, scans, manifest checks,
smoke test; tag-driven release; rollback runbook; 31 tests; 34 recorded checks.

## Why a Deployment
The app is replaceable: kill the pod, a new one with the same image starts. Deployment gives
rolling updates, revision history and `rollout undo`. StatefulSet is for pods that need a stable
name and their own volume each; that would split the learning memory per pod (D1).

## Pod, ReplicaSet, Deployment, Service
Pod: the running container (plus shared network/volumes). ReplicaSet: keeps N identical pods for
one pod template. Deployment: owns ReplicaSets; a new image makes a new ReplicaSet and shifts pods
across; old ReplicaSets stay (5 kept) for rollback. Service: stable name and IP
(`reasoning-engine.reasoning-engine.svc`) that sends traffic only to Ready pods matching the label.

## Probes in this project
startup `/_stcore/health` (60 s budget) → then liveness `/_stcore/health` every 15 s (3 fails =
restart) and readiness `python -m engine.health` every 10 s (3 fails = removed from Service).
Shown live: corrupting `vector_meta.json` made the pod 0/1 and emptied the endpoints; restoring
it brought it back. No restart, because liveness only checks the web server.

## CI/CD
PR or push → 4 jobs: test (ruff, pytest, build stores, readiness, benchmark), security (gitleaks on
full history, pip-audit), manifests (kustomize + kubeconform + policy: non-root, read-only, probes,
limits, no `:latest`, no Secret), image (hadolint, build, smoke test, trivy). Actions pinned to SHAs.
Tag `v1.2.0` → release job pushes `ghcr.io/<owner>/reasoning-engine:1.2.0`. Deploy = edit
`newTag`, commit, `kubectl apply -k`. Not done: the GitHub-hosted run itself (needs a push).

## How do you know which version is running?
Three places that must agree: pod image tag, `python -m engine.health` → `version` + `git_sha`
(baked from build args), image OCI labels. `scripts/verify-release.sh <v>` checks tag, Ready and
reported version for every serving pod. Dashboard caption and every log line show it too.

## Release and rollback — what was actually shown
0.1.0-dev → 0.2.0-dev: surge pod started, old pod left only after new one was Ready, verified.
Bad tag 0.3.0-missing: `ErrImagePull`, `ProgressDeadlineExceeded`, old pod kept serving;
`rollout undo` fixed it. Then `undo --to-revision=1` back to 0.1.0-dev, then re-applied Git state.
A poller hitting the Service every 0.5 s saw zero failures through all of that.
After an emergency undo, Git must be reverted too, or the next apply re-deploys the bad tag.

## Requests and limits
Requests 100m CPU / 192Mi: what the scheduler reserves. Limits 1 CPU / 512Mi: CPU is throttled
above 1 core; memory above 512Mi gets the container OOM-killed. Measured: 225m CPU, 50Mi just after
a benchmark run. Memory has headroom for Streamlit sessions and pandas tables; the CPU limit allows
bursts during retrieval. Requests < limits → Burstable QoS.

## Secrets
Groq key only as a Kubernetes Secret created with `kubectl`, injected as an env var, `optional`.
Never in Git (gitignore, gitleaks in CI and pre-commit), never in the image (runtime env only;
the build-time proxy CA used a BuildKit secret mount). Rotation = re-create Secret + rollout restart.
Limit: Secrets are base64 in etcd unless the cluster encrypts at rest.

## Observability and troubleshooting
JSON logs: `ask.completed` with latency/grounded/confidence, `teach.completed`,
`llm.fallback_to_stub` (silent degradation), `ask.failed` with traceback. `kubectl logs`,
`kubectl describe` (probe failures name the broken file), `kubectl get events`, `kubectl top`.
Lesson learned during testing: requests run with `kubectl exec python ...` log to the exec
session, not to `kubectl logs`; real traffic had to go through the Service (ui-probe.py).

## Evidence of correct behaviour
`docs/verification.md` (34 checks) and `docs/evidence/` (raw output). Two checks failed first and
were fixed: plain `pytest` could not import the package in a clean env; `verify-release.sh`
counted a terminating pod. Both fixes are separate commits.

## Trade-offs to defend
- One replica (D1) vs availability. - emptyDir default (D2) vs losing lessons on restart.
- Hashing embedder in the image (D6) vs answer quality. - Logs only (D10) vs metrics.
- Readiness checks stores but not the LLM (D4): an LLM outage degrades answers, never restarts pods.

## Scaling and dependency failure
Scale-out is blocked by file-based state, not by Kubernetes. Fix order: move lessons to a DB,
then replicas: 2 + PodDisruptionBudget + HPA on CPU. Groq down: `llm.chat` retries 3× with
backoff, then every stage falls back to the stub; users still get grounded answers, lower quality.
Stores broken: readiness fails, pod leaves the Service, rollout stalls instead of shipping it.

## Remaining limitations / future work (not done)
Build on `python:3.12-slim` and trivy unverified here; no auth in front of the dashboard;
no `/metrics`; no image signing or digest pin; no multi-replica support; Groq path untested.
