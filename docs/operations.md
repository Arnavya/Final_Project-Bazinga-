# Operations runbook

Namespace `reasoning-engine`, Deployment `reasoning-engine`, Service `reasoning-engine` (port 80 → 8501).
All commands assume `kubectl` points at the target cluster.

## 1. Version identification

A running release is identified three ways, and all three must agree:

| Where | How to read it |
|---|---|
| Image tag | `kubectl -n reasoning-engine get deploy reasoning-engine -o jsonpath='{.spec.template.spec.containers[0].image}'` |
| App's own report | `kubectl -n reasoning-engine exec deploy/reasoning-engine -- python -m engine.health` → `version`, `git_sha` |
| Image labels | `docker image inspect <image> --format '{{json .Config.Labels}}'` → `org.opencontainers.image.version`, `.revision` |

The dashboard caption also shows `version` and the short SHA. Every JSON log line carries `version`.

Version scheme: semantic version tags `vMAJOR.MINOR.PATCH` on Git; the image tag is the same
number without the `v`; `-dev` suffixes are local builds that never leave a laptop or test cluster.
`:latest` is never deployed (CI fails the build if a manifest uses it).

## 2. Release procedure

```bash
# 1. Tag the commit that passed CI
git tag -a v1.2.0 -m "v1.2.0" && git push origin v1.2.0      # release.yml publishes the image

#    Local cluster without a registry: build and load the image yourself
docker build -t reasoning-engine:1.2.0 --build-arg APP_VERSION=1.2.0 --build-arg GIT_SHA=$(git rev-parse HEAD) .
docker save reasoning-engine:1.2.0 | sudo k3s ctr images import -       # k3s
# kind load docker-image reasoning-engine:1.2.0                         # kind
# minikube image load reasoning-engine:1.2.0                            # minikube

# 2. Point the manifests at the new tag (Git is the record of what is deployed)
#    edit k8s/base/kustomization.yaml: newTag: 1.2.0   (newName: ghcr.io/<owner>/reasoning-engine for GHCR)
git commit -am "deploy: reasoning-engine 1.2.0"

# 3. Apply and record why
kubectl apply -k k8s/base
kubectl -n reasoning-engine annotate deploy/reasoning-engine kubernetes.io/change-cause="release 1.2.0" --overwrite

# 4. Verify
scripts/verify-release.sh 1.2.0
```

How the rollout behaves: `maxSurge: 1, maxUnavailable: 0`. The new pod starts next to the old one;
the old pod keeps serving until the new pod passes its startup probe (Streamlit up) and readiness
probe (stores present, parseable, writable). If the new pod never becomes Ready, the old pod is
never removed and `rollout status` fails after `progressDeadlineSeconds` (180 s).

With the `persistent` overlay the strategy is `Recreate` (single writer on one volume), so a
release has a short outage while the new pod starts.

## 3. Rollback

```bash
kubectl -n reasoning-engine rollout history deploy/reasoning-engine          # list revisions
kubectl -n reasoning-engine rollout undo deploy/reasoning-engine             # previous revision
kubectl -n reasoning-engine rollout undo deploy/reasoning-engine --to-revision=2
scripts/verify-release.sh <previous-version>
```

`revisionHistoryLimit: 5` keeps five old ReplicaSets, so five releases can be undone without
rebuilding anything. After an emergency `rollout undo`, bring Git back in line
(`git revert` the deploy commit) so the next `kubectl apply -k` does not re-deploy the bad version.

Learning memory and rollback: lessons live in the state volume, not in the image, so a rollback
keeps them. A release that changes the lesson file format would need a migration; none exists today.

## 4. Logs and observability

Logs are JSON on stdout (`LOG_FORMAT=json`), one event per line.

| Event | Level | Fields | Meaning |
|---|---|---|---|
| `ask.completed` | INFO | `qid`, `q_len`, `latency_ms`, `grounded`, `confidence`, `provider` | one question answered |
| `ask.failed` | ERROR | `qid`, `exc` | exception while answering |
| `teach.completed` | INFO | `qid`, `action`, `similarity_v1`, `similarity_v2` | expert correction learned |
| `benchmark.completed` | INFO | `scenarios`, `duration_ms` | full benchmark run |
| `llm.fallback_to_stub` | WARNING | `version`, `error` | LLM call failed; answer built by heuristics |
| `rerank.unavailable`, `embeddings.fallback` | WARNING | `reason` | optional models missing (expected in the image) |

`qid` is a 12-character hash of the question. Question text is not logged.

```bash
kubectl -n reasoning-engine logs deploy/reasoning-engine --since=1h
kubectl -n reasoning-engine logs deploy/reasoning-engine | grep '"event": "ask.completed"' \
  | python3 -c 'import sys,json; l=[json.loads(x)["latency_ms"] for x in sys.stdin]; print(len(l), "asks, max", max(l), "ms")'
kubectl -n reasoning-engine logs deploy/reasoning-engine | grep -c llm.fallback_to_stub   # silent degradation
kubectl -n reasoning-engine logs deploy/reasoning-engine --previous                        # after a restart
kubectl -n reasoning-engine top pod                                                        # needs metrics-server
kubectl -n reasoning-engine get events --sort-by=.lastTimestamp
```

No metrics endpoint or dashboard stack is deployed. For one Streamlit pod, log-derived numbers and
`kubectl top` are enough; a Prometheus exporter is listed in `docs/decisions.md` as future work.

## 5. Troubleshooting

| Symptom | Check | Likely cause / fix |
|---|---|---|
| Pod `0/1 Running`, not in endpoints | `kubectl describe pod` → `Readiness probe failed: {... "problems": [...]}` | the JSON names the bad store file; delete the pod (state is re-seeded on emptyDir) or fix the file on the PVC |
| `CrashLoopBackOff` | `kubectl logs --previous` | startup error in `app.py`; roll back |
| Restarts with reason `OOMKilled` | `kubectl describe pod` → Last State | raise `limits.memory` (512Mi) or reduce concurrent sessions |
| `ImagePullBackOff` / `ErrImageNeverPull` | `kubectl describe pod` | tag not in the registry / not loaded into the local cluster; old pod keeps serving; `rollout undo` |
| Answers worse than expected, no errors | `grep llm.fallback_to_stub` in logs | Groq unreachable, rate-limited or bad key; check Secret and egress |
| UI loses state on refresh / reconnects | number of replicas, Service affinity | Streamlit sessions live in one pod; keep `sessionAffinity: ClientIP` |
| Lessons gone after restart | volume type | base uses `emptyDir`; use `k8s/overlays/persistent` |

## 6. Secrets

```bash
# create or rotate the Groq key (never committed; never in a manifest file)
kubectl -n reasoning-engine create secret generic reasoning-engine-secrets \
  --from-literal=GROQ_API_KEY='<key>' --dry-run=client -o yaml | kubectl apply -f -
kubectl -n reasoning-engine rollout restart deploy/reasoning-engine    # env vars are read at start
```

Without the Secret the pod still starts (`optional: true`) and runs in offline stub mode.
