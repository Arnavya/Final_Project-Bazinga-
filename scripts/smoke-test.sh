#!/usr/bin/env bash
# Smoke-test a built image with production-like hardening.
#   scripts/smoke-test.sh reasoning-engine:dev [host-port]
# Checks: liveness endpoint, readiness check, non-root UID, read-only code, one question
# answered end to end, and the dashboard script rendering without exceptions.
set -euo pipefail

IMAGE="${1:?usage: smoke-test.sh IMAGE [PORT]}"
PORT="${2:-18501}"
NAME="re-smoke-$$"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:8501" \
  --read-only --tmpfs /tmp --tmpfs /app/stores:uid=10001,gid=10001 \
  --cap-drop ALL --security-opt no-new-privileges \
  "$IMAGE" >/dev/null

echo "== waiting for liveness"
for i in $(seq 1 60); do
  if [ "$(curl -s --noproxy '*' "http://127.0.0.1:${PORT}/_stcore/health" || true)" = "ok" ]; then
    echo "PASS liveness after ${i}s"; break
  fi
  if [ "$i" = 60 ]; then echo "FAIL liveness"; docker logs "$NAME"; exit 1; fi
  sleep 1
done

echo "== readiness"
docker exec "$NAME" python -m engine.health

echo "== runs as non-root"
uid="$(docker exec "$NAME" id -u)"
[ "$uid" != "0" ] && echo "PASS uid=$uid" || { echo "FAIL running as root"; exit 1; }

echo "== code is read-only"
if docker exec "$NAME" sh -c 'touch /app/engine/.w' 2>/dev/null; then
  echo "FAIL code directory writable"; exit 1
else
  echo "PASS code directory read-only"
fi

echo "== one question end to end"
docker exec "$NAME" python -c "
import pipeline
a = pipeline.ask('Why was the v2.1 release delayed?')
assert a['grounded'], a
print('PASS ask grounded=%s confidence=%s' % (a['grounded'], a['confidence']))
" 2>&1 | grep -v '^\[rerank\]'

echo "== dashboard script renders"
docker exec "$NAME" python -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
assert not at.error, [e.value for e in at.error]
print('PASS app.py rendered, tabs=%d' % len(at.tabs))
" 2>&1 | grep -E '^(PASS|Traceback|AssertionError)' || { echo "FAIL app render"; exit 1; }

echo "ALL SMOKE CHECKS PASSED"
