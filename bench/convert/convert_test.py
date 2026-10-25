#!/usr/bin/env python3
"""End-to-end conversion test: every share-link shape, through Conduit's API, on both cores, against a real
Xray server. Runs in the tester container (stdlib only); prints a table and exits non-zero on any mismatch.
"""
import base64
import hashlib
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "http://172.29.0.30:7782/api"
SERVER = "172.29.0.10"
TARGET = ("172.29.0.20", 80)
U = "6f1c2b0e-6a4e-4a39-9f4f-3c3c1f0b7d11"
SS2022_KEY = "YctPZ6U7xPPcU+gp3u+0tx/tRizJN9K8y+uKlW2qjlI="

cert_hash = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open("/shared/cert.pem").read())).hexdigest()
reality_pub = open("/shared/reality.pub").read().strip()
TLS = f"sni=node.lab&allowInsecure=1&pcs={cert_hash}"


def vmess(d):
    return "vmess://" + base64.b64encode(json.dumps(d).encode()).decode()


# name, link, expected on sing-box, expected on Xray ("ok" or "rejected")
CASES = [
    ("vless ws + ?ed=2048", f"vless://{U}@{SERVER}:9001?type=ws&security=none&path=%2Fws%3Fed%3D2048#c1", "ok", "ok"),
    ("vless tcp tls, no type=", f"vless://{U}@{SERVER}:9002?security=tls&{TLS}#c2", "ok", "ok"),
    ("vless grpc tls", f"vless://{U}@{SERVER}:9003?type=grpc&serviceName=lab-grpc&security=tls&{TLS}#c3", "ok", "ok"),
    ("vless reality vision", f"vless://{U}@{SERVER}:9004?type=tcp&security=reality&sni=node.lab&fp=chrome&pbk={reality_pub}&sid=6ba85179e30d4fc2&flow=xtls-rprx-vision#c4", "ok", "ok"),
    ("vmess ws tls", vmess({"v": "2", "ps": "c5", "add": SERVER, "port": "9005", "id": U, "aid": "0", "net": "ws", "type": "none", "path": "/vm", "tls": "tls", "sni": "node.lab", "allowInsecure": "1", "pcs": cert_hash}), "ok", "ok"),
    ("vmess tcp http-header", vmess({"v": "2", "ps": "c6", "add": SERVER, "port": 9006, "id": U, "aid": 0, "net": "tcp", "type": "http", "path": "/h", "host": "node.lab", "tls": ""}), "rejected", "ok"),
    ("trojan, encoded password", f"trojan://{urllib.parse.quote('p@ss:word', safe='')}@{SERVER}:9007?{TLS}#c7", "ok", "ok"),
    ("ss aes-256-gcm (SIP002)", "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:pa$$word").decode().rstrip("=") + f"@{SERVER}:9008#c8", "ok", "ok"),
    ("ss 2022 (plain userinfo)", f"ss://2022-blake3-aes-256-gcm:{urllib.parse.quote(SS2022_KEY, safe='')}@{SERVER}:9009#c9", "ok", "ok"),
    ("vless httpupgrade", f"vless://{U}@{SERVER}:9010?type=httpupgrade&path=%2Fup&security=none#c10", "ok", "ok"),
    ("vless xhttp", f"vless://{U}@{SERVER}:9011?type=xhttp&path=%2Fx&security=none&mode=auto#c11", "rejected", "ok"),
]


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:  # e.g. nginx's HTML 502 while the API is still starting
            return e.code, {}
    except OSError:
        return 0, {}


def through_proxy(port=8081, n=3):
    """n plain-HTTP requests to the target through the proxy; True when all return 200."""
    for _ in range(n):
        try:
            s = socket.create_connection(("172.29.0.30", port), timeout=8)
            s.settimeout(8)
            # Real Host header: cores that sniff may route to the Host name instead of the CONNECT address
            s.sendall(f"CONNECT {TARGET[0]}:{TARGET[1]} HTTP/1.1\r\nHost: {TARGET[0]}\r\n\r\n".encode())
            if b" 200" not in s.recv(256):
                return False
            s.sendall(f"GET / HTTP/1.1\r\nHost: {TARGET[0]}\r\nConnection: close\r\n\r\n".encode())
            data = b""
            while b"\r\n" not in data:
                chunk = s.recv(256)
                if not chunk:
                    break
                data += chunk
            s.close()
            if b" 200" not in data.split(b"\r\n")[0]:
                return False
        except OSError:
            return False
    return True


def check_domains_and_switch(token, rows):
    """Domains rules survive a core switch, and a switch the active node can't run on is refused unchanged."""
    failures = 0

    def row(name, ok, detail=""):
        nonlocal failures
        failures += not ok
        rows.append(("both", name, "ok", "ok" if ok else "FAILED", "PASS" if ok else "MISMATCH", detail))

    # Active node is xhttp on Xray (last case): switching to sing-box must be refused and change nothing
    status, body = call("PUT", "/settings", {"core_type": "sing-box"}, token)
    core_now = call("GET", "/settings", token=token)[1].get("core_type")
    row("refuse switch for unrunnable node", status == 400 and core_now == "xray", str(body.get("detail", ""))[:70])

    call("POST", "/nodes", {"share_link": CASES[0][1], "activate": True}, token)  # vless ws: runs on both
    for d in reversed(call("GET", "/domains", token=token)[1]["domains"]):
        call("DELETE", f"/domains/{d['id']}", token=token)
    call("POST", "/domains", {"type": "domain_suffix", "value": "example.org", "outbound": "direct"}, token)
    call("POST", "/domains", {"type": "exact", "value": "x.example.net", "outbound": "proxy"}, token)
    call("POST", "/domains/bulk", {"text": "*.google.com\n*youtube*", "outbound": "proxy"}, token)
    on_xray = sorted((d["type"], d["value"], d["outbound"]) for d in call("GET", "/domains", token=token)[1]["domains"])
    status, _ = call("PUT", "/settings", {"core_type": "sing-box"}, token)
    time.sleep(1.5)
    on_sb = sorted((d["type"], d["value"], d["outbound"]) for d in call("GET", "/domains", token=token)[1]["domains"])
    row("domains carried xray -> sing-box", status == 200 and on_xray == on_sb and len(on_sb) == 4, f"{len(on_sb)} rules")
    row("proxy works after switch", through_proxy())
    status, _ = call("PUT", "/settings", {"core_type": "xray"}, token)
    time.sleep(1.5)
    back = sorted((d["type"], d["value"], d["outbound"]) for d in call("GET", "/domains", token=token)[1]["domains"])
    row("domains carried sing-box -> xray", status == 200 and back == on_xray)
    status, _ = call("PUT", "/settings", {"node_mode": "auto"}, token)
    time.sleep(2)
    row("xray auto mode (balancer) works", status == 200 and through_proxy())
    call("PUT", "/settings", {"node_mode": "manual"}, token)
    return failures


def main():
    for _ in range(120):
        status, body = call("POST", "/auth/login", {"username": "admin", "password": "admin"})
        if status == 200:
            break
        time.sleep(0.5)
    token = body["token"]
    rows, failures = [], 0
    for core in ("sing-box", "xray"):
        call("PUT", "/settings", {"core_type": core}, token)
        for name, link, exp_sb, exp_xray in CASES:
            expected = exp_sb if core == "sing-box" else exp_xray
            status, body = call("POST", "/nodes", {"share_link": link, "activate": True}, token)
            if status != 200:
                got, detail = "rejected", str(body.get("detail", ""))[:70]
            else:
                time.sleep(1.5)
                got = "ok" if through_proxy() else "FAILED"
                detail = ""
            mark = "PASS" if got == expected else "MISMATCH"
            failures += mark != "PASS"
            rows.append((core, name, expected, got, mark, detail))
    failures += check_domains_and_switch(token, rows)
    width = max(len(r[1]) for r in rows)
    for core, name, expected, got, mark, detail in rows:
        print(f"{core:8}  {name:{width}}  expected {expected:8}  got {got:8}  {mark:8}  {detail}")
    print(f"\n{len(rows) - failures}/{len(rows)} as expected")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
