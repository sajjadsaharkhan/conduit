# Conduit

A Docker-based proxy client using **sing-box** or **Xray** that exposes **HTTP** and **SOCKS5** proxies. **Frontend and backend run separately**: Web UI on port 80, API on port 8000. This avoids SPA loading issues.

## Features

- **Proxy**: HTTP (8080) and SOCKS5 (1080) inside the backend container
- **Web UI**: Admin panel (login with username/password) to manage subscription, nodes, domains, and settings — served by its own container (nginx)
- **Subscription**: Paste a subscription URL; the app fetches it every 1 minute, parses nodes (vmess, vless, trojan, shadowsocks), runs a latency check, and uses the best node
- **Domains**: Only traffic to domains you add in the UI goes through the proxy; all other traffic is direct
- **Manual config**: Paste a single share link (e.g. `vless://...`) or JSON to use without a subscription
- **SQLite**: All settings and data stored in `/data` (persisted via Docker volume)

## Quick start (Docker)

1. **Build and run** (backend + frontend as two services)

   ```bash
   docker compose up -d --build
   ```

   **Building behind a proxy** (e.g. corporate HTTP/HTTPS proxy): set build args and proxy env so the build can download sing-box and Xray binaries:

   ```bash
   export HTTP_PROXY=http://proxy.example.com:8080
   export HTTPS_PROXY=http://proxy.example.com:8080
   docker compose build --build-arg HTTP_PROXY=$HTTP_PROXY --build-arg HTTPS_PROXY=$HTTPS_PROXY
   docker compose up -d
   ```

   Or build the backend image only with proxy:

   ```bash
   docker build \
     --build-arg HTTP_PROXY=http://proxy.example.com:8080 \
     --build-arg HTTPS_PROXY=http://proxy.example.com:8080 \
     -t conduit-backend \
     -f Dockerfile .
   ```

   (Replace `http://proxy.example.com:8080` with your proxy URL. Use `http://` even for HTTPS_PROXY if the proxy does HTTP CONNECT.)

2. **Open Web UI**

   - **URL: http://localhost** (port 80 — frontend container; nginx proxies `/api` to the backend)
   - **Default login: username `admin`, password `admin`**
   - Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `docker-compose.yml` for the **backend** service to change.

3. **Configure**: Subscription URL, Domains, Nodes in the Web UI. The app refreshes the subscription every 1 minute and picks the best node by latency.

4. **Use the proxy on your machine**: Set system or app proxy to HTTP/HTTPS `localhost:8080` and SOCKS5 `localhost:1080`. Only traffic to the domains you added uses the proxy; the rest is direct. On the **Dashboard**, the **“How to use the proxy”** panel shows OS-specific steps and a **curl** tab with sample commands. In **Settings** you can set the **Proxy display host** (e.g. your server IP or hostname) so those instructions show the correct address instead of `127.0.0.1`.

## Quick start (development — frontend standalone)

Run the frontend and backend **separately** so the UI loads reliably:

1. **Backend** (terminal 1):

   ```bash
   cd backend && pip install -r requirements.txt && DATABASE_PATH=./data/conduit.db uvicorn main:app --reload --port 8000
   ```

2. **Frontend** (terminal 2):

   ```bash
   cd frontend && npm install && npm run dev
   ```

3. Open **http://localhost:5173** (Vite dev server). The frontend proxies `/api` to `http://127.0.0.1:8000`, so the login and all API calls work. Log in with **admin** / **admin**.

## Ports

| Port | Service  | Purpose     |
|------|----------|-------------|
| 80   | frontend | Web UI (nginx) |
| 8000 | backend  | API         |
| 8080 | backend  | HTTP proxy  |
| 1080 | backend  | SOCKS5      |

## Settings (Web UI)

- **Proxy display host** (Settings → Proxy display host): Host or IP shown in the Dashboard **“How to use the proxy”** panel (Linux, macOS, Windows, and **curl** tabs). Used only for display so you can set your server IP or hostname; default is `127.0.0.1`. The **curl** tab shows sample commands using the HTTP and SOCKS5 proxy (e.g. `curl -x http://HOST:PORT https://example.com -I`).
- **Proxy authentication** (Settings → Proxy authentication): Optional username and password for the HTTP and SOCKS5 proxies. When set, clients must send these credentials to use the proxy (HTTP Basic / SOCKS5 auth). Leave both empty for no authentication. Applies to both sing-box and Xray cores; config is reapplied when you save.

## Testing the proxy

**Telnet** to port 8080 will show "Connected" then "Connection closed by foreign host". That is normal: the HTTP proxy accepts the TCP connection but expects an HTTP request (e.g. `CONNECT` or `GET`). When you send nothing, it closes the connection.

To verify the proxy works:

```bash
# HTTP proxy (port 8080)
curl -x http://localhost:8080 https://example.com -I

# SOCKS5 (port 1080)
curl -x socks5://localhost:1080 https://example.com -I
```

If the core is running and you have a valid node + proxy domains configured, these should return HTTP headers from example.com.

## Environment (backend service)

- `ADMIN_USERNAME` – First-time admin username (default: `admin`)
- `ADMIN_PASSWORD` – First-time admin password (default: `admin`)
- `DATABASE_PATH` – SQLite file path (default: `/data/conduit.db`)
- `SINGBOX_CONFIG_PATH` – sing-box config path (default: `/data/singbox_config.json`)
- `JWT_SECRET` – Secret for auth tokens (optional; generated if not set)
- `SINGBOX_CLASH_API` – Set to `1` (or `true`/`yes`) to enable **experimental** Clash API for sing-box so the Dashboard **Usage** panel shows upload/download. Requires a sing-box build that includes the experimental Clash API (e.g. built with `with_clash_api`). If your sing-box does not support the `experimental` config block, leave this unset.

## Docker image builds (GitHub Actions)

On push to `main` or `master`, GitHub Actions build the backend and frontend images for `linux/amd64` and `linux/arm64` and push them to GitHub Container Registry (if not a pull request).

- **Backend:** `ghcr.io/<owner>/<repo>/backend:main` (or `:master`, `:sha-xxx`)
- **Frontend:** `ghcr.io/<owner>/<repo>/frontend:main` (or `:master`, `:sha-xxx`)

To use the built images with Docker Compose, set the image names in `docker-compose.yml` or pull manually:

```bash
docker pull ghcr.io/sajjadsaharkhan/conduit/backend:main
docker pull ghcr.io/sajjadsaharkhan/conduit/frontend:main
```

## Development

See **Quick start (development — frontend standalone)** above. Backend runs on port 8000; frontend runs on port 5173 and proxies `/api` to the backend. Use `DATABASE_PATH=./data/conduit.db` and create a `data/` directory so the backend can create the SQLite DB and default admin user.

## License

MIT
