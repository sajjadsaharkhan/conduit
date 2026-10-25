#!/usr/bin/env bash
# Conduit production deploy. Runs on the server from the repo clone (e.g. /opt/conduit).
#
# deploy pulls a pinned image from GHCR, backs up /data, switches the container, waits until the
# UI, API and proxy ports answer, and rolls back automatically (image + data) if they don't.
# Every command supports --dry-run. Full procedure: docs/runbook.md
#
#   deploy/deploy.sh deploy [TAG] [--dry-run] [--yes] [--no-backup] [--no-auto-rollback] [--no-pull] [--force]
#   deploy/deploy.sh rollback [--with-data] [--dry-run] [--yes]
#   deploy/deploy.sh status | history | logs [-f]
#   deploy/deploy.sh backup [--dry-run]
#   deploy/deploy.sh restore FILE [--dry-run] [--yes]
#   deploy/deploy.sh migrate-legacy [--dry-run] [--yes]   # remove the old conduit_backend/conduit_frontend containers
#
# Settings come from .env next to the compose files (CONDUIT_IMAGE, CONDUIT_TAG, CONDUIT_NETWORK, ports).
# Environment overrides: CONDUIT_STATE_DIR, CONDUIT_BACKUP_DIR, KEEP_BACKUPS (10), HEALTH_TIMEOUT (120s),
# CONDUIT_PROJECT / CONDUIT_CONTAINER (default "conduit"; a second instance on the same host needs its own),
# CONDUIT_IGNORE_LEGACY=1 (old conduit_backend/conduit_frontend containers belong to something else).
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=$ROOT/.env
STATE_DIR=${CONDUIT_STATE_DIR:-$ROOT/.deploy}
BACKUP_DIR=${CONDUIT_BACKUP_DIR:-$STATE_DIR/backups}
HISTORY=$STATE_DIR/history.tsv   # timestamp  status  tag  image_id  backup_file
KEEP_BACKUPS=${KEEP_BACKUPS:-10}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-120}
PROJECT=${CONDUIT_PROJECT:-conduit}
CONTAINER=${CONDUIT_CONTAINER:-conduit}
export CONDUIT_CONTAINER=$CONTAINER   # used by the compose files
DEFAULT_IMAGE=ghcr.io/sajjadsaharkhan/conduit

DRY_RUN=0 ASSUME_YES=0 AUTO_ROLLBACK=1 DO_BACKUP=1 DO_PULL=1 FORCE=0 WITH_DATA=0 FOLLOW=0
ARGS=()

# --- output -------------------------------------------------------------------------------------
step() { printf '\n==> %s\n' "$*"; }
log() { printf '    %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Run a command, or only print it under --dry-run.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '    [dry-run]'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

confirm() {
  [ "$ASSUME_YES" = 1 ] || [ "$DRY_RUN" = 1 ] && return 0
  [ -t 0 ] || die "$1 needs confirmation; re-run with --yes"
  local answer
  read -r -p "$1 [y/N] " answer
  [ "$answer" = y ] || [ "$answer" = Y ] || die "aborted"
}

# --- .env (read as data, never sourced or printed) ----------------------------------------------
env_get() {
  local value
  value=$(sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -n 1)
  value=${value%\"}; value=${value#\"}; value=${value%\'}; value=${value#\'}
  printf '%s' "${value:-${2:-}}"
}

env_set() {
  if [ "$DRY_RUN" = 1 ]; then log "[dry-run] set $1=$2 in .env"; return; fi
  local tmp
  tmp=$(mktemp "$ENV_FILE.XXXXXX")
  if grep -q "^$1=" "$ENV_FILE"; then
    awk -v k="$1" -v v="$2" 'index($0, k "=") == 1 { print k "=" v; next } { print }' "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp"; printf '%s=%s\n' "$1" "$2" >>"$tmp"
  fi
  chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

image_repo() { env_get CONDUIT_IMAGE "$DEFAULT_IMAGE"; }
network() { env_get CONDUIT_NETWORK bridge; }
web_port() { env_get CONDUIT_WEB_PORT 7782; }

proxy_ports() {
  local key port
  for key in CONDUIT_HYBRID_HTTP_PORT:8080 CONDUIT_FULL_HTTP_PORT:8081 CONDUIT_HYBRID_SOCKS_PORT:1080 CONDUIT_FULL_SOCKS_PORT:1081; do
    port=$(env_get "${key%%:*}" "${key##*:}")
    [ -n "$port" ] && [ "$port" != 0 ] && printf '%s\n' "$port"
  done
}

compose_file() {
  case "$(network)" in
    bridge) printf '%s' "$ROOT/docker-compose.deploy.yml" ;;
    host) printf '%s' "$ROOT/docker-compose.host.yml" ;;
    *) die "CONDUIT_NETWORK must be bridge or host" ;;
  esac
}

compose() { run docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$(compose_file)" "$@"; }

# --- container and image facts ------------------------------------------------------------------
container_exists() { docker inspect "$CONTAINER" >/dev/null 2>&1; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = true ]; }
container_image_id() { docker inspect -f '{{.Image}}' "$CONTAINER" 2>/dev/null || true; }
image_id() { docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || true; }

data_volume() {
  local name
  name=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$CONTAINER" 2>/dev/null || true)
  printf '%s' "${name:-${PROJECT}_conduit_data}"
}

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# --- state --------------------------------------------------------------------------------------
LOCK_DIR=$STATE_DIR/lock
acquire_lock() {
  [ "$DRY_RUN" = 1 ] && return
  mkdir -p "$STATE_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || die "another deploy is running (remove $LOCK_DIR if it crashed)"
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
}

record() {  # status tag image_id backup
  [ "$DRY_RUN" = 1 ] && return
  mkdir -p "$STATE_DIR"
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "${4:--}" >>"$HISTORY"
}

# Successful deploys, newest first: "tag image_id backup"
ok_deploys() {
  [ -f "$HISTORY" ] || return 0
  awk -F'\t' '$2 == "ok" { l[n++] = $3 "\t" $4 "\t" $5 } END { for (i = n - 1; i >= 0; i--) print l[i] }' "$HISTORY"
}

# --- checks -------------------------------------------------------------------------------------
preflight() {
  step "Preflight"
  command -v docker >/dev/null || die "docker is not installed"
  docker info >/dev/null 2>&1 || die "cannot reach the Docker daemon (are you in the docker group?)"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (docker compose ...)"
  command -v curl >/dev/null || die "curl is required for health checks"
  [ -f "$ENV_FILE" ] || die "$ENV_FILE not found: cp .env.example .env and edit it"
  [ -f "$(compose_file)" ] || die "$(compose_file) not found"
  if [ "$(network)" = host ] && [ "$(uname -s)" != Linux ]; then
    die "CONDUIT_NETWORK=host only works on Linux"
  fi
  if [ "${CONDUIT_IGNORE_LEGACY:-0}" != 1 ] && { docker inspect conduit_backend >/dev/null 2>&1 || docker inspect conduit_frontend >/dev/null 2>&1; }; then
    die "old two-container setup is still present: run 'deploy/deploy.sh migrate-legacy' first (data is kept)"
  fi
  if ! container_running; then
    local port
    for port in $(web_port) $(proxy_ports); do
      port_open "$port" && die "port $port is already in use on this host"
    done
  fi
  local free_kb
  # Best effort: Docker's root dir is not visible from the host on Docker Desktop
  free_kb=$(df -Pk "$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /)" 2>/dev/null | awk 'NR==2 {print $4}') || true
  if [ -n "$free_kb" ] && [ "$free_kb" -lt 2097152 ]; then warn "less than 2 GB free for Docker images"; fi
  log "docker, compose, .env and ports OK (network: $(network))"
}

registry_login() {
  local user token
  user=$(env_get GHCR_USER); token=$(env_get GHCR_TOKEN)
  [ -n "$token" ] || return 0
  if [ "$DRY_RUN" = 1 ]; then log "[dry-run] docker login ghcr.io -u <GHCR_USER> --password-stdin (token from .env)"; return; fi
  printf '%s' "$token" | docker login ghcr.io -u "$user" --password-stdin >/dev/null || die "GHCR login failed (check GHCR_USER/GHCR_TOKEN)"
  log "logged in to ghcr.io"
}

# Wait until the container runs, the UI and API answer, and the expected proxy ports accept connections.
wait_healthy() {
  local expected=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) web api port missing
  step "Health check (up to ${HEALTH_TIMEOUT}s)"
  [ "$DRY_RUN" = 1 ] && { log "[dry-run] would wait for UI :$(web_port), API and ports: ${expected:-none}"; return 0; }
  while [ $SECONDS -lt $deadline ]; do
    missing=""
    container_running || missing="container"
    web=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$(web_port)/" || true)
    [ "$web" = 200 ] || missing="$missing ui"
    api=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$(web_port)/api/auth/me" || true)
    [ "$api" = 401 ] || missing="$missing api"   # 401 = API up and enforcing auth
    for port in $expected; do port_open "$port" || missing="$missing port:$port"; done
    if [ -z "$missing" ]; then
      log "healthy: UI 200, API 401 (auth enforced), ports ${expected:-none needed}"
      return 0
    fi
    sleep 2
  done
  warn "not healthy after ${HEALTH_TIMEOUT}s; still failing: $missing"
  docker logs --tail 40 "$CONTAINER" 2>&1 | sed 's/^/    | /' >&2 || true
  return 1
}

# Proxy ports that answer now; after a deploy the same ones must answer again.
listening_proxy_ports() {
  local port out=""
  container_running || return 0
  for port in $(proxy_ports); do port_open "$port" && out="$out $port"; done
  printf '%s' "${out# }"
}

# --- backup / restore ---------------------------------------------------------------------------
# Online backup: a consistent SQLite copy (sqlite3 backup API inside the container) plus every file in /data.
# Sets BACKUP_FILE ("-" when skipped).
BACKUP_FILE=-
do_backup() {
  local image=$1 vol old
  BACKUP_FILE=-
  [ "$DO_BACKUP" = 1 ] || { log "backup skipped (--no-backup)"; return; }
  # Unique name: two backups in the same second (e.g. restore's safety copy) must never overwrite each other
  local stamp n=0
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  BACKUP_FILE="$BACKUP_DIR/conduit-data-$stamp.tar.gz"
  while [ -e "$BACKUP_FILE" ]; do n=$((n + 1)); BACKUP_FILE="$BACKUP_DIR/conduit-data-$stamp-$n.tar.gz"; done
  vol=$(data_volume)
  step "Backup /data (volume $vol)"
  run mkdir -p "$BACKUP_DIR"
  if container_running; then
    run docker exec "$CONTAINER" python3 -c "import sqlite3; s = sqlite3.connect('/data/conduit.db'); d = sqlite3.connect('/data/.backup-conduit.db'); s.backup(d); d.close()"
  fi
  run docker run --rm --entrypoint tar -v "$vol:/data:ro" -v "$BACKUP_DIR:/backup" "$image" czf "/backup/$(basename "$BACKUP_FILE")" -C /data .
  [ "$DRY_RUN" = 1 ] && return
  chmod 600 "$BACKUP_FILE"
  log "saved $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
  # Keep the newest KEEP_BACKUPS archives
  ls -1t "$BACKUP_DIR"/conduit-data-*.tar.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | while read -r old; do rm -f "$old"; done
}

do_restore() {
  local file=$1 image=$2 vol
  [ -f "$file" ] || [ "$DRY_RUN" = 1 ] || die "backup not found: $file"
  vol=$(data_volume)
  step "Restore /data from $(basename "$file")"
  compose stop
  run docker run --rm --entrypoint sh -v "$vol:/data" -v "$(cd "$(dirname "$file")" && pwd):/backup:ro" "$image" -c \
    "find /data -mindepth 1 -delete && tar xzf /backup/$(basename "$file") -C /data && if [ -f /data/.backup-conduit.db ]; then mv /data/.backup-conduit.db /data/conduit.db && rm -f /data/conduit.db-wal /data/conduit.db-shm; fi"
}

# Point TAG at a specific local image (tags like :main move; the old image is still on disk) and start it.
switch_to() {
  local tag=$1 id=$2 repo
  repo=$(image_repo)
  [ -n "$id" ] && [ "$id" != - ] && run docker tag "$id" "$repo:$tag"
  env_set CONDUIT_TAG "$tag"
  compose up -d --pull never --remove-orphans --force-recreate
}

# --- commands -----------------------------------------------------------------------------------
cmd_deploy() {
  local tag=${ARGS[0]:-$(env_get CONDUIT_TAG latest)} repo prev_tag prev_id new_id backup ports
  repo=$(image_repo)
  acquire_lock
  preflight
  registry_login
  case "$tag" in latest | main) warn "'$tag' is a moving tag; pin a release (v1.2.3) or commit sha for reproducible rollbacks" ;; esac

  prev_tag=$(env_get CONDUIT_TAG)
  prev_id=$(container_image_id)
  ports=$(listening_proxy_ports)

  step "Pull $repo:$tag"
  if [ "$DO_PULL" = 1 ]; then
    local out
    out=$(run docker pull "$repo:$tag" 2>&1) || die "pull failed: $(printf '%s' "$out" | tail -n 1) (tag pushed by CI? private package needs GHCR_USER/GHCR_TOKEN)"
    printf '%s\n' "$out" | tail -n 2 | sed 's/^/    /'
  fi
  new_id=$(image_id "$repo:$tag")
  [ -n "$new_id" ] || [ "$DRY_RUN" = 1 ] || die "image $repo:$tag not found locally"
  if [ -n "$prev_id" ] && [ "$new_id" = "$prev_id" ] && [ "$FORCE" = 0 ]; then
    log "$repo:$tag is already running (${new_id:7:12}); nothing to do (use --force to recreate)"
    return 0
  fi
  log "current: ${prev_tag:-none} (${prev_id:7:12})  ->  new: $tag (${new_id:7:12})"
  confirm "Deploy $repo:$tag?"

  BACKUP_FILE=-
  if container_exists; then do_backup "$repo:$tag"; fi
  backup=$BACKUP_FILE

  step "Switch to $tag"
  env_set CONDUIT_TAG "$tag"
  compose up -d --pull never --remove-orphans

  if wait_healthy "$ports"; then
    record ok "$tag" "$new_id" "$backup"
    step "Deployed $tag"
    return 0
  fi

  record failed "$tag" "$new_id" "$backup"
  if [ "$AUTO_ROLLBACK" = 0 ] || [ -z "$prev_id" ]; then
    die "deploy of $tag is unhealthy$([ -z "$prev_id" ] && echo ' (first deploy, nothing to roll back to)'); see logs above"
  fi
  step "Automatic rollback to ${prev_tag} (${prev_id:7:12})"
  if [ "$backup" != - ]; then do_restore "$backup" "$prev_id"; fi
  switch_to "$prev_tag" "$prev_id"
  if wait_healthy "$ports"; then
    record rolledback "$prev_tag" "$prev_id" "$backup"
    die "deploy of $tag failed health checks; rolled back to $prev_tag (image and data)"
  fi
  die "deploy of $tag failed AND rollback to $prev_tag is unhealthy: follow 'Rollback failed' in docs/runbook.md"
}

cmd_rollback() {
  local current target tag id backup ports
  acquire_lock
  preflight
  current=$(ok_deploys | sed -n 1p)
  target=$(ok_deploys | sed -n 2p)
  [ -n "$target" ] || die "no earlier successful deploy in $HISTORY to roll back to"
  tag=$(printf '%s' "$target" | cut -f1); id=$(printf '%s' "$target" | cut -f2)
  # The backup taken just before the current version went live is the previous version's data
  backup=$(printf '%s' "$current" | cut -f3)
  [ -n "$(image_id "$id")" ] || [ "$DRY_RUN" = 1 ] || die "image ${id:7:12} for $tag was pruned; deploy it again with: deploy/deploy.sh deploy $tag"
  log "rolling back $(printf '%s' "$current" | cut -f1) -> $tag (${id:7:12})$([ "$WITH_DATA" = 1 ] && echo ", restoring data from $backup")"
  [ "$WITH_DATA" = 0 ] || [ "$backup" != - ] || die "no backup was taken for the current deploy; roll back without --with-data"
  confirm "Roll back to $tag?$([ "$WITH_DATA" = 1 ] && echo ' Data changes since that deploy will be lost.')"
  ports=$(listening_proxy_ports)
  [ "$WITH_DATA" = 1 ] && do_restore "$backup" "$id"
  switch_to "$tag" "$id"
  wait_healthy "$ports" || die "rolled back to $tag but it is unhealthy; see logs above"
  record ok "$tag" "$id" -
  step "Rolled back to $tag"
}

cmd_backup() {
  container_exists || die "no $CONTAINER container: nothing to back up"
  do_backup "$(container_image_id)"
  [ "$DRY_RUN" = 1 ] || step "Backup done: $BACKUP_FILE"
}

cmd_restore() {
  local file=${ARGS[0]:-}
  [ -n "$file" ] || die "usage: deploy/deploy.sh restore FILE"
  acquire_lock
  container_exists || die "no $CONTAINER container; deploy first, then restore"
  confirm "Replace ALL current data with $(basename "$file")?"
  local ports id
  ports=$(listening_proxy_ports); id=$(container_image_id)
  do_backup "$id"   # safety copy of what is being replaced
  do_restore "$file" "$id"
  compose up -d --pull never
  wait_healthy "$ports" || die "restored, but unhealthy; see logs above"
  step "Restored $(basename "$file")"
}

cmd_status() {
  local id
  printf 'Image:    %s:%s\n' "$(image_repo)" "$(env_get CONDUIT_TAG -)"
  printf 'Network:  %s\n' "$(network)"
  if container_exists; then
    id=$(container_image_id)
    printf 'Running:  %s (image %s, started %s, restarts %s)\n' \
      "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" "${id:7:12}" \
      "$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" | cut -c1-19)" \
      "$(docker inspect -f '{{.RestartCount}}' "$CONTAINER")"
  else
    printf 'Running:  no container\n'
  fi
  printf 'UI:       HTTP %s on :%s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$(web_port)/" || true)" "$(web_port)"
  printf 'API:      HTTP %s (401 = up)\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$(web_port)/api/auth/me" || true)"
  local port
  for port in $(proxy_ports); do
    printf 'Port %-5s %s\n' "$port" "$(port_open "$port" && echo open || echo closed)"
  done
  printf 'Backups:  %s in %s\n' "$(ls -1 "$BACKUP_DIR"/conduit-data-*.tar.gz 2>/dev/null | wc -l | tr -d ' ')" "$BACKUP_DIR"
  [ -f "$HISTORY" ] && { printf 'Recent deploys:\n'; tail -n 5 "$HISTORY" | awk -F'\t' '{ printf "  %s  %-10s %-20s %s\n", $1, $2, $3, substr($4, 8, 12) }'; }
  return 0
}

cmd_history() {
  [ -f "$HISTORY" ] || { echo "no deploys recorded yet"; return; }
  awk -F'\t' 'BEGIN { printf "%-20s  %-10s  %-20s  %-12s  %s\n", "time (UTC)", "status", "tag", "image", "backup" }
              { printf "%-20s  %-10s  %-20s  %-12s  %s\n", $1, $2, $3, substr($4, 8, 12), $5 }' "$HISTORY"
}

cmd_logs() { if [ "$FOLLOW" = 1 ]; then docker logs --tail 200 -f "$CONTAINER"; else docker logs --tail 200 "$CONTAINER"; fi; }

cmd_migrate_legacy() {
  local c found=0
  for c in conduit_backend conduit_frontend; do docker inspect "$c" >/dev/null 2>&1 && found=1; done
  [ "$found" = 1 ] || { log "no legacy containers found"; return 0; }
  step "Remove legacy containers (their data volume is kept and reused by the new container)"
  docker inspect -f '    {{.Name}}: {{.Config.Image}}' conduit_backend conduit_frontend 2>/dev/null || true
  confirm "Stop and remove conduit_backend and conduit_frontend?"
  for c in conduit_backend conduit_frontend; do
    docker inspect "$c" >/dev/null 2>&1 && run docker rm -f "$c" >/dev/null
  done
  log "done; now run: deploy/deploy.sh deploy <tag>"
}

usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

main() {
  local cmd=${1:-}
  [ -n "$cmd" ] || usage 1
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --yes | -y) ASSUME_YES=1 ;;
      --no-backup) DO_BACKUP=0 ;;
      --no-auto-rollback) AUTO_ROLLBACK=0 ;;
      --no-pull) DO_PULL=0 ;;
      --force) FORCE=1 ;;
      --with-data) WITH_DATA=1 ;;
      -f | --follow) FOLLOW=1 ;;
      -h | --help) usage 0 ;;
      -*) die "unknown option $1" ;;
      *) ARGS+=("$1") ;;
    esac
    shift
  done
  [ "$DRY_RUN" = 1 ] && printf 'DRY RUN: nothing will be changed\n'
  case "$cmd" in
    deploy) cmd_deploy ;;
    rollback) cmd_rollback ;;
    backup) cmd_backup ;;
    restore) cmd_restore ;;
    status) cmd_status ;;
    history) cmd_history ;;
    logs) cmd_logs ;;
    migrate-legacy) cmd_migrate_legacy ;;
    -h | --help | help) usage 0 ;;
    *) die "unknown command $cmd (see --help)" ;;
  esac
}

main "$@"
