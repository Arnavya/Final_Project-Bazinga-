# Decisions

Each entry: what was chosen, what was rejected, and the cost of the choice.

## D1. Deployment, not StatefulSet, with one replica
Chosen: Deployment, `replicas: 1`.
The app's only state is a handful of JSON/NPZ files rewritten whole on every lesson, with no lock.
A StatefulSet would give each pod its own volume, so lessons taught on pod-0 would never reach
pod-1: two replicas give two different "brains". A shared RWX volume would let two processes
overwrite each other's `lessons.json`. One replica is the honest configuration for this code.
Cost: no redundancy; a pod replacement is a short outage (measured in `docs/evidence/17`).
To scale: move lessons, overrides and answers into a database (SQLite on one writer, or Postgres),
then raise replicas; Service already has session affinity for Streamlit.

## D2. emptyDir by default, PVC as an overlay
Base uses `emptyDir`; `k8s/overlays/persistent` swaps in a 1Gi RWO PVC.
Base works on any cluster with no StorageClass and keeps rolling updates zero-downtime.
The overlay keeps lessons across restarts but must use `Recreate` (RWO + single writer).
Measured both: base 1 lesson → 0 after pod replacement; overlay 1 → 1.

## D3. Rolling update with maxSurge 1, maxUnavailable 0
The new pod must pass readiness before the old one is removed. A broken image or broken stores
never takes the service down; the rollout stalls and `progressDeadlineSeconds: 180` marks it failed.
Verified with a non-existent tag: old pod kept serving, zero failed health polls.

## D4. Three probes, two signals
- startup: `/_stcore/health`, up to 60 s, so a slow first start is not killed by liveness.
- liveness: `/_stcore/health` — restart only if the web server is hung.
- readiness: `python -m engine.health` — stores present, parseable, state dir writable.
Liveness deliberately does not check the stores: a corrupt file is not fixed by a restart loop,
and with emptyDir a restart would also wipe the evidence. Readiness takes the pod out of the
Service instead and the probe message names the broken file.
Not covered by any probe: the LLM being down. The engine silently falls back to the stub; that is
visible only as `llm.fallback_to_stub` in logs. A probe on an external API would restart healthy
pods during a Groq outage.

## D5. Stores built into the image, seeded at start
`data/build_dataset.py` and the ingest run at image build time into `/app/stores-seed`; the
entrypoint copies missing files into the writable `STORES_DIR` and never overwrites existing ones.
Rejected: building at pod start (slower start, needs write access to code), init container
(same image, more YAML, no gain). The build fails if `engine.health` is not ready, so a bad
ingest cannot be shipped.

## D6. Hashing embedder and no torch in the image
`sentence-transformers` pulls torch (hundreds of MB to GB) and downloads models at first use,
which a read-only, egress-restricted pod cannot do. The image pins `EMBEDDING_MODEL=hashing`
at build and run time (vectors must come from the same embedder used to query them).
Cost: weaker retrieval than bge-small. The local `setup.sh` path still uses bge-small.

## D7. Exact pins in a separate requirements file
`requirements.txt` (lower bounds) stays for local development as in the baseline.
`requirements-runtime.txt` pins every package for the image, so a rebuild next month gives the
same image. Dependabot proposes upgrades as reviewable PRs instead of silent drift.

## D8. Secret is optional
`secretKeyRef.optional: true`. Without a key the pod starts and runs the offline stub, which is
the behaviour the app already had. The Secret is created with `kubectl`, never stored as YAML in
the repo; CI fails if a rendered manifest contains a Secret.

## D9. Kustomize, not Helm
One app, one environment, two variants (base, persistent). Kustomize ships with `kubectl` and
keeps plain YAML reviewable. The image tag lives in one line of `kustomization.yaml`, which makes
"what is deployed" a Git diff. Helm would add templating for no current need.

## D10. Logs instead of a metrics stack
JSON events to stdout with latency, groundedness, confidence and fallbacks. With one pod, a
Prometheus + Grafana install would be more infrastructure than application. Future work: expose
`/metrics` (request count, latency histogram, fallback count) via a small sidecar-free exporter
thread and scrape it.

## D11. Question text not logged
Questions may contain internal company information. Logs carry a 12-character SHA-256 prefix to
correlate repeats and the length. The reasoning history in `stores/` still holds full text, as in
the baseline.

## D12. Release image only from tags; deploy is a separate commit
Building on every push to main, but publishing only on `v*.*.*` tags, keeps the registry to real
releases. Deploying is a change to `newTag` that goes through review, so Git history answers
"what ran when". Rejected: auto-deploy from CI (no cluster credentials should live in CI for a
course project, and there is no shared cluster to deploy to).

## D13. Build base as an argument
`ARG BASE_IMAGE=python:3.12-slim`. Allowed the image to be built and tested in an environment
without Docker Hub access, and makes a digest pin or an internal mirror a one-line change.
