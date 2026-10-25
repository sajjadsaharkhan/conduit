# Lab node: a real proxy server (Xray or sing-box, NODE_KIND) with artificial delay (tc netem) on its egress.
FROM debian:bookworm-slim
ARG TARGETARCH
ARG SINGBOX_VER=1.12.23
ARG XRAY_VER=26.2.6
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates iproute2 unzip \
    && curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VER}/sing-box-${SINGBOX_VER}-linux-${TARGETARCH}.tar.gz" \
       | tar -xz -C /usr/local/bin --strip-components=1 \
    && case "${TARGETARCH}" in amd64) xa=64;; arm64) xa=arm64-v8a;; esac \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VER}/Xray-linux-${xa}.zip" -o /tmp/x.zip \
    && unzip -o /tmp/x.zip xray -d /usr/local/bin && rm /tmp/x.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY node-singbox.json node-xray.json /etc/
COPY node-start.sh /usr/local/bin/node-start
CMD ["node-start"]
