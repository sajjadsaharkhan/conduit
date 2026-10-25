# Conduit

**A v2ray / Xray / sing-box proxy client for your server or private network.** Run it as a Docker service, manage your nodes via a web UI, and use HTTP or SOCKS5 proxy only for the domains you choose—so your servers can bypass filters and sanctions without changing desktop or mobile clients.

<p align="center">
  <a href="https://github.com/sajjadsaharkhan/conduit/actions/workflows/docker-build.yml">
    <img src="https://github.com/sajjadsaharkhan/conduit/actions/workflows/docker-build.yml/badge.svg" alt="Docker build" />
  </a>
  <a href="https://www.docker.com/">
    <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat&logo=docker&logoColor=white" alt="Docker" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" />
  </a>
</p>

---

## 📖 Short description

**Conduit** is a **server-side proxy client** for [v2ray](https://www.v2ray.com/), [Xray](https://github.com/XTLS/Xray-core), and [sing-box](https://github.com/SagerNet/sing-box). You add your nodes (share links or outbound JSON), pick the one to use, and it exposes **HTTP** and **SOCKS5** proxies. You configure which domains use the proxy in a web UI; all other traffic stays direct. Ideal for servers in restricted regions that need reliable outbound access.

---

## 🎯 The problem

In many countries, **government filtering or sanctions** block or throttle outbound traffic. **[V2Ray](https://www.v2ray.com/)**, **[Xray](https://github.com/XTLS/Xray-core)** (a v2ray fork), and **[sing-box](https://github.com/SagerNet/sing-box)** are among the most **advanced and reliable** ways to connect through such restrictions—supporting **VLESS**, **VMess**, **Trojan**, **Shadowsocks**, and flexible routing.

The catch: their **clients are built for desktop and mobile**. On **servers** (VPS, homelab, CI runners) you usually need a **single HTTP/SOCKS proxy** that your apps and scripts can use, without installing per-app clients or changing how every service connects.

---

## ✅ Our solution

**Conduit** acts as a **v2ray proxy client** inside your **private network**:

| What you get | How it works |
|--------------|--------------|
| 🐳 **One Docker image** | Web UI, API and core in one container; no manual core config. |
| 🔗 **Your nodes** | Add VMess/VLESS/Trojan/Shadowsocks share links or outbound JSON, ping/test them, and choose which one is active. |
| 🌐 **Hybrid ports (8080 / 1080)** | HTTP and SOCKS5; only traffic to **domains you add** goes through the proxy—everything else is **direct**. |
| 🛡️ **Full-tunnel ports (8081 / 1081)** | HTTP and SOCKS5; **everything** goes through the selected node, Domains rules are ignored. |
| ⚙️ **sing-box or Xray** | Choose in settings; no hand-editing JSON or running core binaries yourself. |

So: **one service, a hybrid and a full-tunnel endpoint, domain-based routing, and a simple UI.** Your server uses it like any other HTTP/SOCKS proxy.

---

## 💡 Why “Conduit”?

A **conduit** is a channel that carries something from one place to another. Here it carries your traffic through the proxy only when needed—by domain—and leaves the rest untouched. The name reflects that focused, configurable flow.

---

## ✨ Features

| Feature | Description |
|--------|-------------|
| 🔌 **HTTP & SOCKS5 proxies** | Hybrid on **8080** / **1080**, full tunnel on **8081** / **1081**; all ports set by env vars; optional proxy authentication. |
| 🖥️ **Web UI** | Admin panel (login with username/password) to manage nodes, domains, and settings; served on port 7782 (nginx, together with `/api`). |
| 🎚️ **Domain-based routing** | Only traffic to domains you add uses the proxy; all other traffic is direct (bypass). |
| 📋 **Node list** | Keep several nodes; Ping (TCP from the server) and Test (real latency/speed through the node) help you pick. Switching only restarts the core when you choose. |
| 🔀 **Dual core support** | **sing-box** or **Xray**; choose in settings. |
| 💾 **SQLite** | All settings and data in `/data` (persisted via Docker volume). |

---

## 🛠 Technologies

### Proxy core

- **[sing-box](https://github.com/SagerNet/sing-box)** — Universal proxy platform (VLESS, VMess, Trojan, Shadowsocks, etc.).
- **[Xray](https://github.com/XTLS/Xray-core)** — Powerful proxy toolkit (v2ray fork); same protocol family.

### Backend

- **[Python](https://www.python.org/)** · **[FastAPI](https://fastapi.tiangolo.com/)** · **[Uvicorn](https://www.uvicorn.org/)** — API server.
- **[SQLite](https://www.sqlite.org/)** via [aiosqlite](https://github.com/omnilib/aiosqlite) — Persistent storage.

### Frontend & design system

- **[React](https://react.dev/)** · **[TypeScript](https://www.typescriptlang.org/)** · **[Vite](https://vitejs.dev/)** — App and build tooling.
- **[Tailwind CSS](https://tailwindcss.com/)** · **[tailwindcss-animate](https://github.com/jamiebuilds/tailwindcss-animate)** — Utility-first styling and animations.
- **[Radix UI](https://www.radix-ui.com/)** — Accessible, unstyled primitives (Dialog, Select, Tabs, Label, etc.) for a consistent component set.
- **[CVA](https://cva.pages.dev/) (class-variance-authority)** · **[tailwind-merge](https://github.com/dcastil/tailwind-merge)** · **[clsx](https://github.com/lukeed/clsx)** — Variant-based components and class merging (shadcn-style).
- **[Lucide React](https://lucide.dev/)** — Icon set.

The UI is built with a **component-based design system**: Radix primitives for behavior and accessibility, Tailwind for layout and visuals, and CVA for button/alert/label variants—giving a clean, consistent admin panel without a heavy UI framework.

### Deploy

- **[Docker](https://www.docker.com/)** · **Docker Compose** — Run backend and frontend as services; images published to [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

---

## 🚀 Quick start (pre-built images, no build)

Use the images published to **GitHub Container Registry** (no build on your machine):

```bash
cp .env.example .env   # optional: change ports or the initial admin login
docker compose -f docker-compose.deploy.yml up -d
```

Then open **http://localhost:7782** (default login: `admin` / `admin`). Add a node on the Proxy page and configure domains in the UI. Use the hybrid proxy at **HTTP** `localhost:8080` / **SOCKS5** `localhost:1080`, or the full tunnel at **HTTP** `localhost:8081` / **SOCKS5** `localhost:1081`.

> Upgrading from the two-image setup (`conduit/backend` + `conduit/frontend`): use the new compose file. The image is now `ghcr.io/sajjadsaharkhan/conduit:main` and the UI moved from port 80 to 7782. The `conduit_data` volume is reused as-is. Subscriptions were removed: on first start, subscription nodes and settings are deleted; add the nodes you want to keep on the Proxy page.

---

## 🔨 Quick start (build locally)

If you prefer to build images yourself:

```bash
docker compose up -d --build
```

**Behind a corporate proxy:** set `HTTP_PROXY` and `HTTPS_PROXY`, then:

```bash
docker compose build --build-arg HTTP_PROXY=$HTTP_PROXY --build-arg HTTPS_PROXY=$HTTPS_PROXY
docker compose up -d
```

---

## 🔌 Ports

All ports are set in `.env` (see `.env.example`); the compose files and the UI read them from there. Set a proxy port to `0` to turn it off.

| Default | Env var | Purpose |
|---------|---------|---------|
| **7782** | `CONDUIT_WEB_PORT` | Web UI + `/api` (nginx) |
| **8080** | `CONDUIT_HYBRID_HTTP_PORT` | HTTP proxy, hybrid (Domains rules) |
| **1080** | `CONDUIT_HYBRID_SOCKS_PORT` | SOCKS5, hybrid (Domains rules) |
| **8081** | `CONDUIT_FULL_HTTP_PORT` | HTTP proxy, full tunnel |
| **1081** | `CONDUIT_FULL_SOCKS_PORT` | SOCKS5, full tunnel |
| 8000 | `CONDUIT_API_PORT` | API (internal only, behind nginx) |

The full-tunnel ports open only once a node is selected, so their traffic can never fall back to direct.

---

## ⚙️ Configure proxy usage

- **Proxy display host** (Settings) — Host or IP shown in the Dashboard “How to use the proxy” panel (e.g. your server IP or hostname instead of `127.0.0.1`).
- **Proxy authentication** (Settings) — Optional username/password for HTTP and SOCKS5; leave empty for no auth.

Point your system or apps at a hybrid port (`http://HOST:8080`, `socks5://HOST:1080`) to send only the domains you added through the proxy, or at a full-tunnel port (`http://HOST:8081`, `socks5://HOST:1081`) to send everything through it. The Proxy page lists all four endpoints with copyable URLs.

---

## 🧪 Test the proxy

```bash
# Hybrid: shows your server's own IP unless ifconfig.me is in your Domains list
curl -x http://localhost:8080 https://ifconfig.me
curl -x socks5h://localhost:1080 https://ifconfig.me

# Full tunnel: always shows the node's IP
curl -x http://localhost:8081 https://ifconfig.me
curl -x socks5h://localhost:1081 https://ifconfig.me
```

---

## ⚡ Performance

Built for low latency under heavy load: live node switching without restarts, an **Auto (fastest)** mode that
picks the node with the lowest real delay, optional per-node **multiplex** (connection pooling), quiet logs and raised
container limits. `docker-compose.host.yml` runs Conduit with host networking.

See **[docs/performance.md](docs/performance.md)** for what each option does, the server-side settings
multiplex needs, host tuning (BBR), and the latency benchmark and lab in `bench/`.

---

## 🔁 sing-box and Xray

Nodes are stored as a core-neutral model and converted for whichever core runs: share links (VLESS, VMess, Trojan,
Shadowsocks incl. 2022 and SIP003 plugins) and pasted sing-box or Xray outbound JSON. Supported on both cores:
TCP, WebSocket, gRPC, httpupgrade, TLS (SNI, ALPN, uTLS fingerprint) and Reality (incl. XTLS Vision).
Xray only: xhttp and TCP HTTP-header obfuscation. sing-box only: HTTP/2 transport and Shadowsocks plugins.
Conduit refuses a node, or a core switch, that the core can't run, and says why. Switching core keeps your
Domains rules. Note: Xray 25+ dropped `allowInsecure`; use `pcs=` (pinned certificate SHA-256) or sing-box.

---

## 👨‍💻 Development

Run backend and frontend separately:

```bash
# Backend (terminal 1)
cd backend && pip install -r requirements.txt && DATABASE_PATH=./data/conduit.db uvicorn main:app --reload --port ${CONDUIT_API_PORT:-8000}

# Frontend (terminal 2)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**; the dev server proxies `/api` to the backend. Log in with **admin** / **admin**.

---

## 🗺 Roadmap: traffic scenarios (domains)

Planned behavior for **domain-based traffic** (user-configurable):

| Mode | Behavior |
|------|----------|
| 🟢 **Whitelist** (current) | Bypass all traffic *except* the specified domains; only those domains use the proxy. |
| 🔴 **Blacklist** | Send all traffic through the proxy *except* the specified domains; those go direct. |
| 🔵 **Proxy all** | Send all traffic through the proxy (no domain bypass). |

Today the app implements the **whitelist** style. The other modes are on the roadmap so you can choose the scenario that fits your environment.

---

## 📋 Environment (backend)

| Variable | Description |
|----------|-------------|
| `ADMIN_USERNAME` | First-time admin username (default: `admin`) |
| `ADMIN_PASSWORD` | First-time admin password (default: `admin`) |
| `DATABASE_PATH` | SQLite path (default: `/data/conduit.db`) |
| `SINGBOX_CONFIG_PATH` | sing-box config path (default: `/data/singbox_config.json`) |
| `JWT_SECRET` | Secret for auth tokens (optional; if unset, generated once and kept in `/data/.jwt_secret` so logins survive restarts) |

sing-box's Clash API is always on, bound to `127.0.0.1:9092` inside the container (live node switching and traffic stats).
---

## 📄 License

MIT
