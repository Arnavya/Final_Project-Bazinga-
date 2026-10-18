# Security controls

What is protected, how, and how each control was checked. "Verified" means the check ran in this
repository's local test environment (see `docs/verification.md`).

## Assets and threats

| Asset | Threat | Control |
|---|---|---|
| Groq API key | committed to Git; baked into an image; read by other workloads | never in Git or images; Kubernetes Secret created out of band; `optional` so the app runs without it |
| Learning memory (`stores/`) | tampering; loss | only the app UID can write; code is read-only; optional PVC |
| Cluster | compromised pod escalating | non-root, no capabilities, no privilege escalation, seccomp, read-only root FS, no SA token, NetworkPolicy |
| Users' questions | leaking through logs | logs carry a hash and length, not the text |
| Supply chain | vulnerable or tampered dependencies / actions | exact pins, pip-audit, trivy, SHA-pinned actions, Dependabot |

## Controls

### Secrets
- `.env`, `*.env` gitignored (baseline) and excluded from the Docker build context (`.dockerignore`).
- `k8s/**/secret*.yaml` gitignored; CI fails if a rendered manifest contains a `kind: Secret`.
- Key enters the pod only as an env var from `reasoning-engine-secrets` (`docs/operations.md` §6).
- Build-time proxy CA is passed as a BuildKit secret mount, not a build arg or `COPY`, so it is
  not in any layer. Verified: no `/run/secrets` and no proxy CA in the built image.
- gitleaks scans the full Git history in CI and in the optional pre-commit hook.
  Verified: `gitleaks git` and `gitleaks dir` → no leaks.

### Container
- Runs as UID/GID 10001 (`USER 10001:10001`), application code root-owned and read-only.
- Only `/app/stores` is writable by the app user.
- Allow-list `.dockerignore`: decks, PDFs, screenshots, `.git`, `.venv`, `.env` never enter the context.
- Streamlit: telemetry off, XSRF protection on, no stack traces in the browser, file watcher off.
- Verified: smoke test runs the container with `--read-only --cap-drop ALL --security-opt no-new-privileges`.

### Kubernetes
- Namespace enforces Pod Security Admission `restricted`; the Deployment was admitted.
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
  `readOnlyRootFilesystem: true`, `seccompProfile: RuntimeDefault`.
- `automountServiceAccountToken: false`; no Role or RoleBinding. Verified: no token path in the pod.
- Service is `ClusterIP` only; nothing is exposed outside the cluster by default.
- NetworkPolicy: ingress only on 8501; egress only DNS and TCP 443 to non-private addresses.
  Verified: pod cannot reach the API server (10.43.0.1:443) with the policy, can without it.
- Resource limits cap the blast radius of a runaway session (1 CPU, 512Mi).

### Supply chain
- `requirements-runtime.txt`: every runtime package pinned to an exact version. Verified: pip-audit → no known vulnerabilities.
- All GitHub Actions pinned to commit SHAs; `permissions: contents: read` by default;
  `packages: write` only in the tag-triggered release job.
- Dependabot opens weekly update PRs for pip, Docker and Actions.
- trivy scans the image for fixable CRITICAL/HIGH CVEs in CI. Not run locally (database download blocked).

## Not covered (known gaps)
- Base image pinned by tag, not by digest.
- No image signing (cosign) or SBOM attestation.
- No authentication in front of the dashboard; anyone who can reach the Service can ask and teach.
  Put it behind an authenticating Ingress / proxy before exposing it.
- Secrets are base64 in etcd unless the cluster enables encryption at rest.
- `pip` remains inside the runtime virtualenv.
