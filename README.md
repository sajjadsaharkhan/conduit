# Conduit

**A v2ray / Xray / sing-box proxy client for your server or private network.** Run it as a Docker service, manage subscriptions and nodes via a web UI, and use HTTP or SOCKS5 proxy only for the domains you choose—so your servers can bypass filters and sanctions without changing desktop or mobile clients.

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

**Conduit** is a **server-side proxy client** for [v2ray](https://www.v2ray.com/), [Xray](https://github.com/XTLS/Xray-core), and [sing-box](https://github.com/SagerNet/sing-box). It fetches subscription links, picks the best node by latency, and exposes **HTTP** and **SOCKS5** proxies. You configure which domains use the proxy in a web UI; all other traffic stays direct. Ideal for servers in restricted regions that need reliable outbound access.

---

## 🎯 The problem

In many countries, **government filtering or sanctions** block or throttle outbound traffic. **[V2Ray](https://www.v2ray.com/)**, **[Xray](https://github.com/XTLS/Xray-core)** (a v2ray fork), and **[sing-box](https://github.com/SagerNet/sing-box)** are among the most **advanced and reliable** ways to connect through such restrictions—supporting **VLESS**, **VMess**, **Trojan**, **Shadowsocks**, and flexible routing.

The catch: their **clients are built for desktop and mobile**. On **servers** (VPS, homelab, CI runners) you usually need a **single HTTP/SOCKS proxy** that your apps and scripts can use, without installing per-app clients or changing how every service connects.

---

## ✅ Our solution

**Conduit** acts as a **v2ray proxy client** inside your **private network**:

| What you get | How it works |
|--------------|--------------|
| 🐳 **One Docker stack** | Backend + Web UI; no manual core config. |
| 🔗 **Subscription → best node** | Fetches subscription URL, parses VMess/VLESS/Trojan/Shadowsocks, picks lowest-latency node. |
| 🌐 **HTTP (8080) & SOCKS5 (1080)** | Standard proxy ports; only traffic to **domains you add** goes through the proxy—everything else is **direct**. |
| ⚙️ **sing-box or Xray** | Choose in settings; no hand-editing JSON or running core binaries yourself. |

So: **one service, one proxy endpoint, domain-based routing, and a simple UI.** Your server uses it like any other HTTP/SOCKS proxy.

---

## 💡 Why “Conduit”?

A **conduit** is a channel that carries something from one place to another. Here it carries your traffic through the proxy only when needed—by domain—and leaves the rest untouched. The name reflects that focused, configurable flow.

---

## ✨ Features

| Feature | Description |
|--------|-------------|
| 🔌 **HTTP & SOCKS5 proxies** | Ports **8080** (HTTP) and **1080** (SOCKS5) inside the backend container; optional proxy authentication. |
| 🖥️ **Web UI** | Admin panel (login with username/password) to manage subscription, nodes, domains, and settings; served on port 80. |
| 📡 **Subscription** | Paste a subscription URL; the app fetches it every minute, parses nodes (VMess, VLESS, Trojan, Shadowsocks), runs latency checks, and uses the best node. |
| 🎚️ **Domain-based routing** | Only traffic to domains you add uses the proxy; all other traffic is direct (bypass). |
| 📋 **Manual config** | Paste a single share link (e.g. `vless://...`) or JSON to use without a subscription. |
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
- **[APScheduler](https://apscheduler.readthedocs.io/)** — Subscription refresh and scheduled tasks.

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
# Pull images
docker pull ghcr.io/sajjadsaharkhan/conduit/backend:main
docker pull ghcr.io/sajjadsaharkhan/conduit/frontend:main

# Run with deploy compose
docker compose -f docker-compose.deploy.yml up -d
```

Then open **http://localhost** (default login: `admin` / `admin`). Configure subscription and domains in the UI. Use the proxy at **HTTP** `localhost:8080` and **SOCKS5** `localhost:1080` for the domains you added.

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

| Port | Service  | Purpose        |
|------|----------|----------------|
| **80**   | frontend | Web UI (nginx) |
| **8000** | backend  | API            |
| **8080** | backend  | HTTP proxy     |
| **1080** | backend  | SOCKS5         |

---

## ⚙️ Configure proxy usage

- **Proxy display host** (Settings) — Host or IP shown in the Dashboard “How to use the proxy” panel (e.g. your server IP or hostname instead of `127.0.0.1`).
- **Proxy authentication** (Settings) — Optional username/password for HTTP and SOCKS5; leave empty for no auth.

Point your system or apps at `http://HOST:8080` (HTTP) or `socks5://HOST:1080` (SOCKS5). Only requests to domains you added in the UI go through the proxy.

---

## 🧪 Test the proxy

```bash
# HTTP proxy (port 8080)
curl -x http://localhost:8080 https://example.com -I

# SOCKS5 (port 1080)
curl -x socks5://localhost:1080 https://example.com -I
```

With a valid node and proxy domains configured, these return HTTP headers from the target site.

---

## 👨‍💻 Development

Run backend and frontend separately:

```bash
# Backend (terminal 1)
cd backend && pip install -r requirements.txt && DATABASE_PATH=./data/conduit.db uvicorn main:app --reload --port 8000

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
| `JWT_SECRET` | Secret for auth tokens (optional; auto-generated if unset) |
| `SINGBOX_CLASH_API` | Set to `1` to enable experimental Clash API for usage stats (if your sing-box build supports it) |

---

## 📦 Docker image builds (GitHub Actions)

On push to `main` (or `master`), [GitHub Actions](https://github.com/sajjadsaharkhan/conduit/actions) build backend and frontend for **linux/amd64** and **linux/arm64** and push to [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry):

- **Backend:** `ghcr.io/sajjadsaharkhan/conduit/backend:main`
- **Frontend:** `ghcr.io/sajjadsaharkhan/conduit/frontend:main`

Use these with **docker-compose.deploy.yml** for deploy-only (no local build).

---

## 📄 License

MIT