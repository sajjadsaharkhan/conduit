# Conduit production runbook

How to install, deploy, roll back, back up and troubleshoot Conduit on a production server.
Everything runs on the server through `deploy/deploy.sh` (or the `make` targets that wrap it).

| | |
|---|---|
| **What runs** | One container, `conduit`: nginx (UI + `/api`), the API, and the sing-box or Xray core |
| **Image** | `ghcr.io/sajjadsaharkhan/conduit:<tag>`, built by GitHub Actions |
| **Data** | Docker volume `conduit_conduit_data` → `/data` (SQLite database + core config) |
| **Settings** | `/opt/conduit/.env` (image tag, network mode, ports, initial admin) |
| **Deploy state** | `/opt/conduit/.deploy/` (`history.tsv`, `backups/`) |
| **Ports** (defaults) | 7782 UI/API · 8080 / 1080 hybrid HTTP / SOCKS5 · 8081 / 1081 full-tunnel HTTP / SOCKS5 |

## Which tag to deploy

CI pushes these tags (see `.github/workflows/docker-build.yml`):

| Tag | When | Use on production? |
|---|---|---|
| `v1.2.3` | You push a git tag `v1.2.3` | **Yes**: fixed, easy to read in history |
| `abc1234` (7-char commit) | Every push to `main` | Yes: fixed, for deploying a commit before a release |
| `latest` | Newest `v*` release | No: moves; rollback can't tell versions apart |
| `main` | Every push to `main` | No: moves |

To cut a release: `git tag v1.2.3 && git push origin v1.2.3`, wait for the **Docker build** workflow to pass
(it smoke-tests the image before pushing), then deploy `v1.2.3`.

## 1. First-time setup

Requirements: Linux (amd64 or arm64), Docker 24+, Docker Compose 2.20+, `git`, `curl`, 1 GB RAM, and the ports above free.

```bash
sudo git clone --depth 1 https://github.com/sajjadsaharkhan/conduit.git /opt/conduit
sudo chown -R "$USER" /opt/conduit && cd /opt/conduit
cp .env.example .env && chmod 600 .env
```

Edit `.env`:
- `ADMIN_PASSWORD`: change it before the first start (it is only used to create the first user).
- `CONDUIT_NETWORK`: `bridge` (default) or `host` (lowest latency, Linux only; see `docs/performance.md`).
- Ports, if the defaults clash with something on the host.
- `GHCR_USER` / `GHCR_TOKEN`: only if the GHCR package is private (token with `read:packages`).

Recommended host tuning (BBR, accept queues): see **Host tuning** in `docs/performance.md`.

### Security before going live
- **Proxy ports are an open proxy until you set proxy authentication** (*Settings → Proxy authentication*
  in the UI). Set it right after the first login, or firewall the proxy ports to the clients that use them.
- Expose the UI port (7782) only to admins: firewall it to your IPs or a VPN, or put a TLS reverse proxy in front.

```bash
# Example with ufw: UI only from the admin network, proxies only from the app servers
sudo ufw allow from 203.0.113.0/24 to any port 7782 proto tcp
sudo ufw allow from 10.0.0.0/16 to any port 8080,8081,1080,1081 proto tcp
```

## 2. Deploy

Always dry-run first; it prints every command without changing anything.

```bash
cd /opt/conduit
make update-scripts                 # latest deploy script and compose files
make deploy TAG=v1.2.3 DRY_RUN=1
make deploy TAG=v1.2.3
```

What `deploy` does, in order:
1. **Preflight**: Docker and Compose present, `.env` exists, ports free (if not running yet), disk space, no legacy containers.
2. **Pull** the image for the tag.
3. **Back up** `/data` (consistent SQLite snapshot + every file) to `.deploy/backups/`; the 10 newest are kept.
4. **Switch**: writes `CONDUIT_TAG` into `.env` and recreates the container.
5. **Health check** (up to 120 s): container running, UI returns 200, API returns 401 (up, auth enforced), and every proxy port that was open before is open again.
6. **On failure: automatic rollback** to the previous image *and* the backup from step 3, then health-checks again. The command exits non-zero either way.

Useful options: `YES=1` (no prompt), `deploy/deploy.sh deploy TAG --no-auto-rollback` (leave the broken
version up to debug it), `--force` (recreate even if the tag is already running), `HEALTH_TIMEOUT=300`.

### Verify
```bash
make status
curl -x http://USER:PASS@127.0.0.1:8081 https://ifconfig.me   # full tunnel: shows the node's IP
curl -x http://USER:PASS@127.0.0.1:8080 https://ifconfig.me   # hybrid: your server's IP unless the domain is in Domains
```
In the UI: Dashboard shows the core running and the current node; Proxy → Nodes → **Test** on the active node.

## 3. Roll back

```bash
make rollback                 # previous successful version, keep current data
make rollback WITH_DATA=1     # previous version AND the data as it was before the current version went live
```
- Use plain `rollback` when the new version misbehaves but data is fine (the usual case).
- Use `WITH_DATA=1` when the new version damaged data (for example a bad migration). Changes made in the UI
  since that deploy are lost.
- `make history` shows every deploy, its image, and its backup file.

Rollback re-points the tag at the exact image that ran before, so it works even for moving tags. If that
image was pruned from the host, deploy the old tag again instead: `make deploy TAG=v1.2.2`.

### Rollback failed
If `deploy` says the rollback is unhealthy too:
1. `make logs` and look at the last lines (nginx, uvicorn, sing-box/Xray errors).
2. Common causes: a port taken by another process (`sudo ss -ltnp | grep -E ':(7782|8080|8081|1080|1081)\b'`),
   disk full (`df -h`), Docker daemon problems (`sudo systemctl status docker`).
3. Restore known-good data and version by hand:
   ```bash
   make history                                   # pick the last "ok" tag and its backup
   deploy/deploy.sh restore .deploy/backups/conduit-data-<time>.tar.gz --yes
   make deploy TAG=<last ok tag> YES=1
   ```

## 4. Backups

```bash
make backup                                       # on demand
make restore FILE=.deploy/backups/conduit-data-20261026T101500Z.tar.gz
```
`restore` takes a safety backup of the current data first. Backups contain the admin password hash, proxy
credentials and node links: keep them private (they are written with mode 600).

Copy backups off the server. Example nightly cron job (`crontab -e`):
```cron
15 3 * * * cd /opt/conduit && deploy/deploy.sh backup >/dev/null 2>&1 && rsync -a --delete .deploy/backups/ backup-host:/srv/conduit-backups/
```

## 5. Upgrading from the two-container setup

Older versions ran `conduit_backend` and `conduit_frontend`. Their data volume is reused as-is.
```bash
cd /opt/conduit && make update-scripts
make migrate-legacy        # removes the two old containers; data volume kept
make deploy TAG=v1.2.3
```
The UI moves from port 80 to 7782. Subscriptions no longer exist: subscription nodes are deleted on the first
start; add the nodes you want on the Proxy page.

## 6. Incidents

| Symptom | Check | Action |
|---|---|---|
| UI or API down | `make status`, `make logs` | `docker restart conduit`; if it keeps failing after a deploy, `make rollback` |
| Proxy ports closed, UI fine | Dashboard → core status; `make logs` for sing-box/Xray errors | Core start with the active node: *Core → Start*. If no node is active, select one on the Proxy page. Full-tunnel ports stay closed until a node is active (by design). |
| Requests through the proxy fail | Proxy → Nodes → **Test** on the active node | Switch to another node (live, no restart), or turn on **Auto (fastest)** |
| Slow under load | `docs/performance.md`; *Core → Performance* (Detailed logs must be off) | Multiplex on nodes whose server supports it; host networking; BBR on host and node |
| `too many open files` in logs | `docker exec conduit sh -c 'ulimit -n'` | The compose files set 1,048,576; check you deployed with them, not a hand-written `docker run` |
| Deploy says "another deploy is running" | No deploy actually running (`ps aux | grep deploy.sh`) | `rmdir /opt/conduit/.deploy/lock` |
| `pull access denied` | Package visibility on GitHub | Make the GHCR package public, or set `GHCR_USER` / `GHCR_TOKEN` in `.env` |
| Disk full | `df -h`, `docker system df` | `docker image prune` (keep the images of the last few tags for rollback), trim `.deploy/backups` |

## Command reference

| make | deploy/deploy.sh | |
|---|---|---|
| `make deploy TAG=v1.2.3` | `deploy v1.2.3` | Deploy with backup, health check, auto-rollback |
| `make rollback [WITH_DATA=1]` | `rollback [--with-data]` | Previous successful version |
| `make status` | `status` | Version, container, UI/API/port health, recent deploys |
| `make history` | `history` | Every deploy with image and backup |
| `make logs` / `make logs-follow` | `logs [-f]` | Container logs |
| `make backup` / `make restore FILE=…` | `backup` / `restore FILE` | Data backups |
| `make migrate-legacy` | `migrate-legacy` | Remove the old two-container setup |
| `make update-scripts` | — | `git pull` for scripts and compose files |
| add `DRY_RUN=1` / `YES=1` | `--dry-run` / `--yes` | Print only / no prompts |
