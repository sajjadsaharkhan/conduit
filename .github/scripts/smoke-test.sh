#!/usr/bin/env bash
# Smoke test a built Conduit image: UI, API, adding a node, core config validity and proxy ports.
# Usage: .github/scripts/smoke-test.sh IMAGE
set -euo pipefail
IMAGE=$1
NAME=conduit-smoke
# Uncommon host ports so the test runs next to other services (container ports are the defaults)
B=http://127.0.0.1:27782
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
fail() { echo "SMOKE FAIL: $*"; docker logs --tail 60 "$NAME" || true; exit 1; }

docker run -d --name "$NAME" -p 27782:7782 -p 28080:8080 -p 28081:8081 -p 21080:1080 -p 21081:1081 "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$B/api/auth/me")" = 401 ] && break
  sleep 1
done
[ "$(curl -s -o /dev/null -w '%{http_code}' "$B/")" = 200 ] || fail "UI did not return 200"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$B/api/auth/me")" = 401 ] || fail "API did not come up"

TOKEN=$(curl -sf -X POST "$B/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys, json; print(json.load(sys.stdin)["token"])')
AUTH="Authorization: Bearer $TOKEN"
LINK='vless://6f1c2b0e-6a4e-4a39-9f4f-3c3c1f0b7d11@192.0.2.1:443?type=ws&security=tls&sni=example.com&path=%2Fws%3Fed%3D2048#smoke'
curl -sf -X POST "$B/api/nodes" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"share_link\":\"$LINK\",\"activate\":true}" >/dev/null || fail "adding a node failed"

docker exec "$NAME" sing-box check -c /data/singbox_config.json || fail "generated sing-box config is invalid"
for port in 28080 28081 21080 21081; do
  for _ in $(seq 1 20); do (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && break; sleep 0.5; done
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null || fail "proxy port $port is not listening"
done
curl -sf "$B/api/status" -H "$AUTH" | python3 -c 'import sys, json; d = json.load(sys.stdin); assert d["core"]["running"], d' \
  || fail "core is not running"
echo "smoke test passed"
