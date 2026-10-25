# Conduit: web UI + API + sing-box/Xray in one image.
# nginx serves the UI and /api on CONDUIT_WEB_PORT; the proxy ports are opened by the core itself.

# --- Frontend build ---
# Static assets are the same for every CPU: build them once on the native platform (no emulation)
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

# --- Runtime ---
FROM python:3.11-slim-bookworm
WORKDIR /app

# Install sing-box: pick binary for build architecture (amd64 or arm64)
ARG TARGETARCH
ARG SINGBOX_VER=1.12.23
# Override with e.g. --build-arg XRAY_VER=26.2.6 if the default is outdated
ARG XRAY_VER=26.2.6
# Ensure no HTTP proxy is used during build or at runtime (avoids routing issues)
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= NO_PROXY="*" no_proxy="*"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip nginx gettext-base tini \
    && arch="${TARGETARCH}" \
    && curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VER}/sing-box-${SINGBOX_VER}-linux-${arch}.tar.gz" | tar -xz -C /usr/local/bin --strip-components=1 \
    && case "${TARGETARCH}" in amd64) xray_arch=64;; arm64) xray_arch=arm64-v8a;; *) echo "Unsupported TARGETARCH"; exit 1;; esac \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VER}/Xray-linux-${xray_arch}.zip" -o /tmp/xray.zip \
    && unzip -o /tmp/xray.zip -d /tmp && mv /tmp/xray /usr/local/bin/xray && chmod +x /usr/local/bin/xray && rm /tmp/xray.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && ln -sf /dev/stdout /var/log/nginx/access.log && ln -sf /dev/stderr /var/log/nginx/error.log

COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /app/dist /usr/share/conduit/html
COPY docker/nginx.conf.template /etc/conduit/nginx.conf.template
COPY docker/entrypoint.sh /usr/local/bin/conduit-entrypoint

ENV DATABASE_PATH=/data/conduit.db
ENV SINGBOX_CONFIG_PATH=/data/singbox_config.json
ENV XRAY_CONFIG_PATH=/data/xray_config.json
ENV CONDUIT_WEB_PORT=7782 \
    CONDUIT_API_PORT=8000 \
    CONDUIT_HYBRID_HTTP_PORT=8080 \
    CONDUIT_FULL_HTTP_PORT=8081 \
    CONDUIT_HYBRID_SOCKS_PORT=1080 \
    CONDUIT_FULL_SOCKS_PORT=1081
VOLUME /data

# Documentation only; the real ports come from the CONDUIT_* env vars above.
EXPOSE 7782 8080 8081 1080 1081

ENTRYPOINT ["tini", "-g", "--", "conduit-entrypoint"]
