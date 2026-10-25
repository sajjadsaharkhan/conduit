#!/bin/sh
# Generates the TLS certificate and Reality keys into /shared (read by the test), writes the Xray config, runs Xray.
set -e
mkdir -p /shared
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 \
  -subj "/CN=node.lab" -addext "subjectAltName=DNS:node.lab" \
  -keyout /shared/key.pem -out /shared/cert.pem 2>/dev/null
xray x25519 > /shared/reality.txt
python3 - <<'PY'
import json, re
txt = open("/shared/reality.txt").read()
priv = re.search(r"(?i)private\s*key:\s*(\S+)", txt).group(1)
pub = re.search(r"(?i)(public\s*key|password):\s*(\S+)", txt).group(2)
open("/shared/reality.pub", "w").write(pub)
U = "6f1c2b0e-6a4e-4a39-9f4f-3c3c1f0b7d11"
tls = {"certificates": [{"certificateFile": "/shared/cert.pem", "keyFile": "/shared/key.pem"}]}
def vless(flow=""):
    c = {"id": U}
    if flow: c["flow"] = flow
    return {"clients": [c], "decryption": "none"}
inb = [
    (9001, "vless", vless(), {"network": "ws", "wsSettings": {"path": "/ws"}}),
    (9002, "vless", vless(), {"network": "tcp", "security": "tls", "tlsSettings": tls}),
    (9003, "vless", vless(), {"network": "grpc", "security": "tls", "tlsSettings": tls, "grpcSettings": {"serviceName": "lab-grpc"}}),
    (9004, "vless", vless("xtls-rprx-vision"), {"network": "tcp", "security": "reality", "realitySettings": {
        "dest": "127.0.0.1:9002", "serverNames": ["node.lab"], "privateKey": priv, "shortIds": ["6ba85179e30d4fc2"]}}),
    (9005, "vmess", {"clients": [{"id": U}]}, {"network": "ws", "security": "tls", "tlsSettings": tls, "wsSettings": {"path": "/vm"}}),
    (9006, "vmess", {"clients": [{"id": U}]}, {"network": "tcp", "tcpSettings": {"header": {"type": "http", "request": {"path": ["/h"]}}}}),
    (9007, "trojan", {"clients": [{"password": "p@ss:word"}]}, {"network": "tcp", "security": "tls", "tlsSettings": tls}),
    (9008, "shadowsocks", {"method": "aes-256-gcm", "password": "pa$$word", "network": "tcp,udp"}, None),
    (9009, "shadowsocks", {"method": "2022-blake3-aes-256-gcm", "password": "YctPZ6U7xPPcU+gp3u+0tx/tRizJN9K8y+uKlW2qjlI=", "network": "tcp,udp"}, None),
    (9010, "vless", vless(), {"network": "httpupgrade", "httpupgradeSettings": {"path": "/up"}}),
    (9011, "vless", vless(), {"network": "xhttp", "xhttpSettings": {"path": "/x"}}),
]
inbounds = []
for port, proto, settings, stream in inb:
    i = {"listen": "0.0.0.0", "port": port, "protocol": proto, "settings": settings}
    if stream: i["streamSettings"] = stream
    inbounds.append(i)
json.dump({"log": {"loglevel": "warning"}, "inbounds": inbounds, "outbounds": [{"protocol": "freedom"}]},
          open("/etc/xray.json", "w"), indent=1)
PY
exec xray run -c /etc/xray.json
