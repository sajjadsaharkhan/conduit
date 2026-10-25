#!/usr/bin/env bash
# End-to-end conversion test: every share-link shape through Conduit on both cores, against a real Xray server.
# Usage: bench/convert/run.sh [conduit-image]     (exit code 0 = everything behaved as expected)
set -euo pipefail
cd "$(dirname "$0")"
export CONDUIT_IMAGE=${1:-conduit:bench}
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --build >/dev/null
trap 'docker compose down -v --remove-orphans >/dev/null 2>&1' EXIT
docker compose exec -T tester python3 /bench/convert/convert_test.py
