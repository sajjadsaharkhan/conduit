#!/usr/bin/env python3
"""Drive Conduit's API inside the lab (stdlib only). Runs in the bench container."""
import argparse
import json
import time
import urllib.request

API = "http://172.28.0.30:7782/api"
UUID = "6f1c2b0e-6a4e-4a39-9f4f-3c3c1f0b7d11"
LINK = "vless://" + UUID + "@{ip}:8443?type=ws&security=none&path={path}#lab-{name}"
PATHS = {False: "%2Fws", True: "%2Fws%3Fed%3D2048"}  # --ed: WebSocket early data (path "/ws?ed=2048")
SERVERS = {  # --servers xray: Xray nodes (any Conduit version); sing-box: sing-box nodes (multiplex tests)
    "xray": {"node1": "172.28.0.10", "node2": "172.28.0.11"},
    "sing-box": {"node1": "172.28.0.12", "node2": "172.28.0.13"},
}
NODES = {}


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def login():
    for _ in range(120):
        try:
            return call("POST", "/auth/login", {"username": "admin", "password": "admin"})["token"]
        except Exception:
            time.sleep(0.5)
    raise SystemExit("Conduit API never came up")


def node_ids(token):
    return {n["name"]: n["id"] for n in call("GET", "/nodes", token=token)["nodes"]}


def use_servers(kind, ed=False):
    NODES.update({name: LINK.format(ip=ip, name=name, path=PATHS[ed]) for name, ip in SERVERS[kind].items()})


def setup(args):
    use_servers(args.servers, args.ed)
    token = login()
    for name, link in NODES.items():
        call("POST", "/nodes", {"share_link": link, "activate": name == "node1"}, token)
    ids = node_ids(token)
    if args.multiplex:
        for name in NODES:
            call("PUT", f"/nodes/{ids['lab-' + name]}", {"multiplex": args.multiplex}, token)
    if args.mode:
        call("PUT", "/settings", {"node_mode": args.mode}, token)
    call("POST", "/nodes/select", {"raw_link": NODES["node1"], "node_id": ids["lab-node1"]}, token)
    time.sleep(2)
    st = call("GET", "/status", token=token)
    print(json.dumps({"active": st.get("selected_node_name"), "running": st["core"]["running"]}))


def switch(args):
    use_servers(args.servers, args.ed)
    token = login()
    ids = node_ids(token)
    order = ["node2", "node1"] * args.times
    for name in order[: args.times]:
        time.sleep(args.every)
        t0 = time.perf_counter()
        call("POST", "/nodes/select", {"raw_link": NODES[name], "node_id": ids["lab-" + name]}, token)
        print(json.dumps({"switched_to": name, "ms": round((time.perf_counter() - t0) * 1e3)}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--multiplex", default="")
    s.add_argument("--mode", default="")
    s.add_argument("--servers", choices=SERVERS, default="xray")
    s.add_argument("--ed", action="store_true")
    w = sub.add_parser("switch")
    w.add_argument("--times", type=int, default=3)
    w.add_argument("--every", type=float, default=4)
    w.add_argument("--servers", choices=SERVERS, default="xray")
    w.add_argument("--ed", action="store_true")
    args = ap.parse_args()
    {"setup": setup, "switch": switch}[args.cmd](args)
