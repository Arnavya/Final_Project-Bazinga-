# Baseline submission fields

Copy these three fields into the submission form. They describe the project before any DevOps
change. The final changes are listed separately in `docs/submission-summary.md`.

## 1. Baseline commit

`2ffe22a857d4a5637c5d247518773280722ae9e9` on branch `main`

Permanent URL: `https://github.com/Arnavya/Final_Project-Bazinga-/commit/2ffe22a857d4a5637c5d247518773280722ae9e9`

## 2. Existing deployment and DevOps features

Python 3 Streamlit application (`app.py`, port 8501) with CLI runners (`run_all.py`,
`run_scenario.py`). Deployment was manual and local: `setup.sh` created a virtualenv,
installed `requirements.txt` (lower-bound versions, no pins), generated the synthetic
dataset and the file-based stores, and created `.env` from `.env.example`; the app was then
started with `streamlit run app.py`. Configuration came from environment variables / `.env`;
`.env` was gitignored and the Groq key was never committed. The engine fell back to an
offline stub when no key was set. 25 offline pytest unit tests existed and were run by hand.

There was no Dockerfile, no Kubernetes manifest, no CI/CD pipeline, no versioning or release
process, no health or readiness check, no structured logging, no secret scanning, and no
dependency or image scanning.

## 3. Planned improvements

1. Application operations: readiness check that the stores exist and load, structured JSON
   request logs with latency, a visible app version, configurable state directory.
2. Container: multi-stage Dockerfile with pinned runtime dependencies, stores built at image
   build time, non-root user, health check, `.dockerignore`.
3. Kubernetes: namespace, ConfigMap, optional Secret for the Groq key, Deployment with
   startup/readiness/liveness probes, resource requests and limits, hardened security context,
   ClusterIP Service, NetworkPolicy, Kustomize image pinning.
4. CI/CD: GitHub Actions running lint, tests, image build and smoke test, manifest validation,
   secret scan, dependency audit and image scan; tag-driven release image build.
5. Release control: semantic version tags, image tags tied to Git SHA, rollout verification
   and `kubectl rollout undo` rollback procedure.
6. Verification: recorded evidence of tests, image build, container smoke test, Kubernetes
   deployment, rollout and rollback.
