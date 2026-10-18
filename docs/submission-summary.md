# Submission summary

Baseline fields are in `docs/baseline-submission.md`. This file lists what changed after the baseline.

Commit hashes below are from the local repository. If the branch is replayed onto the upstream
baseline before pushing (`docs/transfer-to-another-laptop.md`), every hash changes; subjects,
authors, author dates and contents stay the same. Use `git log --oneline 2ffe22a..HEAD` after the
push for the final hashes.

## Commits (in order, branch `devops-improvements`)

| Local hash | Author date (UTC) | Subject | Area |
|---|---|---|---|
| `7cf9007` | 2026-10-18 11:55 | docs: record original project baseline and architecture | Architecture |
| `00239e4` | 2026-10-18 11:56 | feat: add readiness check, structured logs and version identification | Operation, observability |
| `c342c2e` | 2026-10-18 12:02 | build: containerize application with pinned deps and non-root runtime | Deployment config |
| `9aa0b10` | 2026-10-18 12:08 | feat: add Kubernetes deployment with probes, limits and hardening | Kubernetes, security |
| `e4e252a` | 2026-10-18 12:13 | ci: add validation workflow and tag-driven release workflow | CI/CD |
| `8e8ed54` | 2026-10-18 12:15 | feat: add release verification, rollback runbook and log-based observability | Release control |
| `94bc2ed` | 2026-10-18 12:21 | fix: skip terminating pods in verify-release.sh | Release control |
| `2876ef2` | 2026-10-18 12:21 | deploy: reasoning-engine 0.2.0-dev | Release control |
| `fef3c0c` | 2026-10-18 12:22 | security: add dependency update automation, pre-commit secret guard and controls record | Security |
| `855c2a8` | 2026-10-18 12:26 | test: record verification results and operational evidence | Verification |
| `7f4321b` | 2026-10-18 12:28 | docs: complete README, decisions, viva notes and transfer guide | Documentation |
| `b256e6d` | 2026-10-18 12:29 | security: allowlist documentation placeholders in gitleaks | Security |
| `cd98f6e` | 2026-10-18 12:31 | docs: update commit list and transfer guide after final review | Documentation |
| `f6dfebb` | 2026-10-18 12:32 | test: add image build log that .gitignore had excluded | Verification |

The commit that adds these two rows is the last one; `git log --oneline ac9abc8..HEAD` is authoritative.

## Changes by rubric area

**Architecture and operation** — `docs/architecture.md` (process, ports, data, config, dependencies,
failure boundaries). `engine/health.py` readiness check; `STORES_DIR` override; version shown in UI.

**Kubernetes** — `k8s/base/`: Namespace (PSA restricted), ServiceAccount (no token), ConfigMap,
Deployment, ClusterIP Service, NetworkPolicy; `k8s/overlays/persistent/` with PVC.

**Deployment configuration** — `Dockerfile` (multi-stage, pinned deps, stores built at build time,
UID 10001, HEALTHCHECK, OCI labels), `docker/entrypoint.sh`, `.dockerignore`,
`.streamlit/config.toml`, `requirements-runtime.txt`, probes/resources/securityContext in the Deployment.

**CI/CD and release delivery** — `.github/workflows/ci.yml` (4 jobs), `.github/workflows/release.yml`
(tag → GHCR), `scripts/smoke-test.sh`.

**Release control** — tag-pinned image in `kustomization.yaml`, RollingUpdate surge 1 / unavailable 0,
revision history 5, progress deadline, `scripts/verify-release.sh`, `docs/operations.md` §1–3.

**Observability and reliability** — `engine/logs.py` JSON events, fallback warnings, log catalogue and
troubleshooting table in `docs/operations.md`, `scripts/ui-probe.py`.

**Security** — `docs/security.md`; secret handling, container and pod hardening, NetworkPolicy,
gitleaks, pip-audit, trivy, SHA-pinned Actions, Dependabot, pre-commit hook.

**Verification** — `docs/verification.md` (34 checks), `docs/evidence/` (raw output).

## Size of change
About 70 files changed and 2,500 lines added (`git diff --stat 2ffe22a..devops-improvements`). Answer logic
untouched: offline benchmark output is identical before and after.
