# Conversion lab server: Xray with one inbound per protocol/transport, a generated TLS cert and Reality keys.
FROM debian:bookworm-slim
ARG TARGETARCH
ARG XRAY_VER=26.2.6
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip openssl python3 \
    && case "${TARGETARCH}" in amd64) xa=64;; arm64) xa=arm64-v8a;; esac \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VER}/Xray-linux-${xa}.zip" -o /tmp/x.zip \
    && unzip -o /tmp/x.zip xray -d /usr/local/bin && rm /tmp/x.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY server-start.sh /usr/local/bin/server-start
CMD ["server-start"]
