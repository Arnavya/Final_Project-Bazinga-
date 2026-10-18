#!/usr/bin/env bash
# Verify that the running Deployment is the release you expect.
#   scripts/verify-release.sh <expected-version> [namespace]
# Exit 0 only if: the rollout completed, every pod runs the expected image tag, every pod is
# Ready, and the app itself reports the expected APP_VERSION.
set -euo pipefail

EXPECTED="${1:?usage: verify-release.sh EXPECTED_VERSION [NAMESPACE]}"
NS="${2:-reasoning-engine}"
DEPLOY="deploy/reasoning-engine"
SEL="app.kubernetes.io/name=reasoning-engine"

echo "== rollout status"
kubectl -n "$NS" rollout status "$DEPLOY" --timeout=180s

echo "== revision history"
kubectl -n "$NS" rollout history "$DEPLOY"

fail=0
for pod in $(kubectl -n "$NS" get pods -l "$SEL" --field-selector=status.phase=Running -o name); do
  image="$(kubectl -n "$NS" get "$pod" -o jsonpath='{.spec.containers[0].image}')"
  ready="$(kubectl -n "$NS" get "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  health="$(kubectl -n "$NS" exec "$pod" -- python -m engine.health || true)"
  version="$(printf '%s' "$health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' 2>/dev/null || echo "?")"
  echo "$pod image=$image ready=$ready app_version=$version"
  [ "${image##*:}" = "$EXPECTED" ] || { echo "  FAIL image tag != $EXPECTED"; fail=1; }
  [ "$ready" = "True" ] || { echo "  FAIL pod not Ready"; fail=1; }
  [ "$version" = "$EXPECTED" ] || { echo "  FAIL app reports $version"; fail=1; }
done

[ "$fail" = 0 ] && echo "RELEASE $EXPECTED VERIFIED" || { echo "RELEASE $EXPECTED NOT VERIFIED"; exit 1; }
