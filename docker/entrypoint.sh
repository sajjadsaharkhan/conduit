#!/bin/bash
# Runs the API (uvicorn, loopback only) and nginx (UI + /api on CONDUIT_WEB_PORT) in one container.
# Exits as soon as either process stops, so Docker's restart policy can take over.
set -euo pipefail

export CONDUIT_WEB_PORT="${CONDUIT_WEB_PORT:-7782}"
export CONDUIT_API_PORT="${CONDUIT_API_PORT:-8000}"

envsubst '${CONDUIT_WEB_PORT} ${CONDUIT_API_PORT}' \
  < /etc/conduit/nginx.conf.template > /etc/nginx/conf.d/conduit.conf
nginx -t -q

cd /app/backend
uvicorn main:app --host 127.0.0.1 --port "$CONDUIT_API_PORT" &
nginx -g 'daemon off;' &

set +e
wait -n
status=$?
echo "conduit: a process exited (status $status), stopping container" >&2
kill -TERM $(jobs -p) 2>/dev/null
wait
exit "$status"
