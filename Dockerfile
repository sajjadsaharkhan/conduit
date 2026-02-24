# Backend only (API + sing-box + Xray). Frontend runs separately.
FROM python:3.11-slim-bookworm
WORKDIR /app

# Install sing-box: pick binary for build architecture (amd64 or arm64)
ARG TARGETARCH
ARG SINGBOX_VER=1.10.0
# Override with e.g. --build-arg XRAY_VER=26.2.6 if the default is outdated
ARG XRAY_VER=26.2.6
# Ensure no HTTP proxy is used during build or at runtime (avoids routing issues)
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= NO_PROXY="*" no_proxy="*"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && arch="${TARGETARCH}" \
    && curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VER}/sing-box-${SINGBOX_VER}-linux-${arch}.tar.gz" | tar -xz -C /usr/local/bin --strip-components=1 \
    && case "${TARGETARCH}" in amd64) xray_arch=64;; arm64) xray_arch=arm64-v8a;; *) echo "Unsupported TARGETARCH"; exit 1;; esac \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VER}/Xray-linux-${xray_arch}.zip" -o /tmp/xray.zip \
    && unzip -o /tmp/xray.zip -d /tmp && mv /tmp/xray /usr/local/bin/xray && chmod +x /usr/local/bin/xray && rm /tmp/xray.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/

ENV DATABASE_PATH=/data/conduit.db
ENV SINGBOX_CONFIG_PATH=/data/singbox_config.json
ENV XRAY_CONFIG_PATH=/data/xray_config.json
VOLUME /data

EXPOSE 8000 8080 1080

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
