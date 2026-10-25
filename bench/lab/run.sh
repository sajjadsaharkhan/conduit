#!/usr/bin/env bash
# Run the latency lab against a Conduit image and write bench/results/<label>.jsonl
# Usage: bench/lab/run.sh <label> [conduit-image] [--servers xray|sing-box] [--ed] [--multiplex h2mux] [--mode auto]
set -euo pipefail
cd "$(dirname "$0")"
LABEL=$1; shift
export CONDUIT_IMAGE=${1:-conduit:bench}; shift || true
OUT=/bench/results/$LABEL.jsonl
rm -f "../results/$LABEL.jsonl"

docker compose down -v --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --build >/dev/null
trap 'docker compose down -v --remove-orphans >/dev/null 2>&1' EXIT
X="docker compose exec -T bench"

$X python3 lab/lab.py setup "$@"
B="python3 bench.py --proxy 172.28.0.30:8081 --target 172.28.0.20:80 --label $LABEL --json $OUT"
$X $B --mode new   -n 30   -c 1   >/dev/null   # warm-up, not recorded
rm -f "../results/$LABEL.jsonl"
$X $B --mode new   -n 100  -c 1
$X $B --mode new   -n 1000 -c 50
$X $B --mode new   -n 2000 -c 200
$X $B --mode new   -n 2500 -c 500
$X $B --mode reuse -n 2000 -c 50
$X $B --mode reuse -n 4000 -c 200

# Node switches under load: count failed requests while switching 3 times
SERVERS=xray; ED=""; for ((i=1; i<=$#; i++)); do [ "${!i}" = --servers ] && { j=$((i+1)); SERVERS=${!j}; }; [ "${!i}" = --ed ] && ED=--ed; done
$X sh -c "python3 bench.py --proxy 172.28.0.30:8081 --target 172.28.0.20:80 --label $LABEL-switch --json $OUT --mode reuse -n 6000 -c 50 & sleep 1; python3 lab/lab.py switch --servers $SERVERS $ED --times 3 --every 3; wait"
echo "results: bench/results/$LABEL.jsonl"
