"""Build sing-box and Xray outbounds from nodes, and the node groups in a core config.

Nodes come in three shapes, all normalized to the model documented in share_links.py first:
  - a parsed share link (vless://, vmess://, trojan://, ss://)
  - a pasted sing-box outbound JSON ({"type": "vless", "server": ...})
  - a pasted Xray outbound JSON ({"protocol": "vless", "settings": ...})
Each core then gets its outbound from the model. A pasted JSON on its own core is used as-is, so fields
Conduit doesn't model survive. Combinations a core can't run raise ValueError with the reason.
"""
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode

from share_links import NETWORK_ALIASES, is_share_link, parse_share_link

PROTOCOLS = ("vless", "vmess", "trojan", "shadowsocks")
TLS_PROTOCOLS = ("vless", "vmess", "trojan")


# --- node model ---------------------------------------------------------------------------------
def node_kind(node: Dict[str, Any]) -> str:
    """"link" (share link model), "sing-box" (sing-box outbound JSON) or "xray" (Xray outbound JSON)."""
    if is_share_link(str(node.get("raw") or "")):  # any stored format; re-parsed from the link
        return "link"
    if "protocol" in node:
        return "xray"
    return "sing-box"


def _model_from_singbox(ob: Dict[str, Any]) -> Dict[str, Any]:
    tls = ob.get("tls") or {}
    reality = tls.get("reality") or {}
    tr = ob.get("transport") or {}
    network = {"http": "h2"}.get(tr.get("type", "tcp"), tr.get("type", "tcp"))
    host = tr.get("host")
    if isinstance(host, list):
        host = host[0] if host else ""
    path = tr.get("path") or "/"
    if network == "ws" and tr.get("max_early_data"):
        path += ("&" if "?" in path else "?") + f"ed={tr['max_early_data']}"
    return {
        "type": ob.get("type"), "server": ob.get("server"), "server_port": int(ob.get("server_port") or 443),
        "uuid": ob.get("uuid", ""), "password": ob.get("password", ""), "method": ob.get("method", ""),
        "plugin": ob.get("plugin", ""), "plugin_opts": ob.get("plugin_opts", ""),
        "alter_id": int(ob.get("alter_id") or 0), "vmess_security": ob.get("security", "auto"),
        "flow": ob.get("flow", ""),
        "network": network, "header_type": "none", "path": path,
        "host": host or (tr.get("headers") or {}).get("Host", ""),
        "service_name": tr.get("service_name", ""), "mode": "",
        "security": "reality" if reality.get("enabled") else "tls" if tls.get("enabled") else "none",
        "sni": tls.get("server_name", ""), "alpn": tls.get("alpn") or [],
        "fingerprint": (tls.get("utls") or {}).get("fingerprint", ""), "insecure": bool(tls.get("insecure")),
        "reality_public_key": reality.get("public_key", ""), "reality_short_id": reality.get("short_id", ""),
        "reality_spider_x": "",
    }


def _model_from_xray(ob: Dict[str, Any]) -> Dict[str, Any]:
    protocol = ob.get("protocol")
    settings = ob.get("settings") or {}
    if protocol in ("vless", "vmess"):
        server = (settings.get("vnext") or [{}])[0]
        user = (server.get("users") or [{}])[0]
    else:
        server = (settings.get("servers") or [{}])[0]
        user = server
    st = ob.get("streamSettings") or {}
    network = NETWORK_ALIASES.get(st.get("network", "tcp"), st.get("network", "tcp"))
    net_settings = st.get({"ws": "wsSettings", "grpc": "grpcSettings", "httpupgrade": "httpupgradeSettings",
                           "xhttp": "xhttpSettings", "tcp": "tcpSettings"}.get(network, ""), {}) or {}
    tls = st.get("tlsSettings") or {}
    reality = st.get("realitySettings") or {}
    security = st.get("security", "none")
    tcp_header = (net_settings.get("header") or {}) if network == "tcp" else {}
    host = net_settings.get("host") or (net_settings.get("headers") or {}).get("Host", "")
    if tcp_header.get("type") == "http":
        req = tcp_header.get("request") or {}
        host = ((req.get("headers") or {}).get("Host") or [""])[0]
        net_settings = {"path": (req.get("path") or ["/"])[0]}
    return {
        "type": protocol, "server": server.get("address"), "server_port": int(server.get("port") or 443),
        "uuid": user.get("id", ""), "password": user.get("password", ""), "method": user.get("method", ""),
        "plugin": "", "plugin_opts": "",
        "alter_id": int(user.get("alterId") or 0), "vmess_security": user.get("security", "auto"),
        "flow": user.get("flow", ""),
        "network": network, "header_type": tcp_header.get("type", "none"),
        "path": net_settings.get("path", "/"), "host": host,
        "service_name": net_settings.get("serviceName", ""),
        "mode": "multi" if net_settings.get("multiMode") else net_settings.get("mode", ""),
        "security": security, "sni": tls.get("serverName") or reality.get("serverName", ""),
        "alpn": tls.get("alpn") or [], "fingerprint": tls.get("fingerprint") or reality.get("fingerprint", ""),
        "insecure": bool(tls.get("allowInsecure")),
        "pinned_cert_sha256": tls.get("pinnedPeerCertSha256", ""),
        "reality_public_key": reality.get("publicKey", ""), "reality_short_id": reality.get("shortId", ""),
        "reality_spider_x": reality.get("spiderX", ""),
    }


def to_model(node: Dict[str, Any]) -> Dict[str, Any]:
    """Any node shape -> the core-neutral model. Share links are re-parsed so stored nodes get parser fixes."""
    kind = node_kind(node)
    if kind == "xray":
        model = _model_from_xray(node)
    elif kind == "link":
        model = parse_share_link(node["raw"]) or {}
    else:
        model = _model_from_singbox(node)
    if model.get("type") not in PROTOCOLS or not model.get("server"):
        raise ValueError(f"Unsupported or incomplete node: {str(node.get('raw') or node)[:80]}")
    return model


# --- sing-box -----------------------------------------------------------------------------------
def _strip_ws_early_data(transport: Dict[str, Any]) -> None:
    """Remove the v2ray/Xray "?ed=N" early-data hint from a sing-box WebSocket path.

    sing-box would send "/ws?ed=2048" as an escaped path, which servers answer with 404. Early data itself
    is not enabled: in testing (bench/lab), sing-box's Sec-WebSocket-Protocol early data lost about half
    of the responses against both Xray and sing-box servers. Xray cores keep "?ed=" and use early data.
    """
    path, _, query = transport["path"].partition("?")
    params = parse_qs(query, keep_blank_values=True)
    if params.pop("ed", None) is None:
        return
    rest = urlencode(params, doseq=True)
    transport["path"] = (path or "/") + (f"?{rest}" if rest else "")


def _singbox_transport(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    net = m.get("network") or "tcp"
    if net == "tcp":
        if m.get("header_type") == "http":
            raise ValueError("TCP with HTTP header obfuscation only works on Xray; switch the core to Xray")
        return None
    if net == "ws":
        t = {"type": "ws", "path": m.get("path") or "/"}
        if m.get("host"):
            t["headers"] = {"Host": m["host"]}
        _strip_ws_early_data(t)
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": m.get("service_name") or ""}
    if net == "h2":
        t = {"type": "http", "path": m.get("path") or "/"}
        if m.get("host"):
            t["host"] = [m["host"]]
        return t
    if net == "httpupgrade":
        t = {"type": "httpupgrade", "path": m.get("path") or "/"}
        if m.get("host"):
            t["host"] = m["host"]
        return t
    raise ValueError(f"The {net} transport isn't supported by sing-box; switch the core to Xray")


def _singbox_tls(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if m.get("security") not in ("tls", "reality"):
        return None
    tls: Dict[str, Any] = {"enabled": True, "server_name": m.get("sni") or m.get("host") or m["server"]}
    if m.get("insecure"):
        tls["insecure"] = True
    if m.get("alpn"):
        tls["alpn"] = m["alpn"]
    fingerprint = m.get("fingerprint") or ("chrome" if m["security"] == "reality" else "")
    if fingerprint:
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
    if m["security"] == "reality":
        if not m.get("reality_public_key"):
            raise ValueError("Reality node without a public key (pbk)")
        tls["reality"] = {"enabled": True, "public_key": m["reality_public_key"], "short_id": m.get("reality_short_id", "")}
    return tls


def singbox_outbound(node: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """sing-box outbound for any node shape."""
    if node_kind(node) == "sing-box":  # pasted sing-box JSON: keep every field
        out = {k: v for k, v in node.items() if k not in ("raw", "remark", "name", "params", "port")}
        out["tag"] = tag
        out.setdefault("server_port", node.get("port"))
        return out
    m = to_model(node)
    out: Dict[str, Any] = {"type": m["type"], "tag": tag, "server": m["server"], "server_port": m["server_port"]}
    if m["type"] == "shadowsocks":
        out.update({"method": m["method"], "password": m["password"]})
        if m.get("plugin"):
            out.update({"plugin": m["plugin"], "plugin_opts": m.get("plugin_opts", "")})
        return out
    if m["type"] == "vless":
        out.update({"uuid": m["uuid"], "packet_encoding": "xudp"})
        if m.get("flow"):
            out["flow"] = m["flow"]
    elif m["type"] == "vmess":
        out.update({"uuid": m["uuid"], "alter_id": m.get("alter_id", 0), "security": m.get("vmess_security") or "auto"})
    else:
        out["password"] = m["password"]
    tls = _singbox_tls(m)
    if tls:
        out["tls"] = tls
    transport = _singbox_transport(m)
    if transport:
        out["transport"] = transport
    return out


# --- Xray ---------------------------------------------------------------------------------------
def _xray_stream(m: Dict[str, Any]) -> Dict[str, Any]:
    net = m.get("network") or "tcp"
    st: Dict[str, Any] = {"network": net, "security": m.get("security") or "none"}
    sni = m.get("sni") or m.get("host") or m["server"]
    if st["security"] == "tls":
        tls: Dict[str, Any] = {"serverName": sni}
        if m.get("pinned_cert_sha256"):
            tls["pinnedPeerCertSha256"] = m["pinned_cert_sha256"]
        elif m.get("insecure"):
            # Xray 25+ removed allowInsecure: skipping certificate checks needs a pinned certificate hash
            raise ValueError(
                "This node skips TLS certificate checks (allowInsecure), which Xray no longer supports; "
                "add the certificate's SHA-256 as pcs= in the link, or switch the core to sing-box"
            )
        if m.get("alpn"):
            tls["alpn"] = m["alpn"]
        if m.get("fingerprint"):
            tls["fingerprint"] = m["fingerprint"]
        st["tlsSettings"] = tls
    elif st["security"] == "reality":
        if not m.get("reality_public_key"):
            raise ValueError("Reality node without a public key (pbk)")
        st["realitySettings"] = {
            "serverName": sni, "fingerprint": m.get("fingerprint") or "chrome",
            "publicKey": m["reality_public_key"], "shortId": m.get("reality_short_id", ""),
            "spiderX": m.get("reality_spider_x", ""),
        }
    path, host = m.get("path") or "/", m.get("host") or ""
    if net == "tcp":
        if m.get("header_type") == "http":
            st["tcpSettings"] = {"header": {"type": "http", "request": {
                "version": "1.1", "method": "GET", "path": [path],
                "headers": {"Host": [host or sni], "User-Agent": ["Mozilla/5.0"], "Accept-Encoding": ["gzip, deflate"],
                            "Connection": ["keep-alive"], "Pragma": ["no-cache"]},
            }}}
    elif net == "ws":
        st["wsSettings"] = {"path": path, "host": host}  # Xray reads "?ed=N" in the path as early data
    elif net == "grpc":
        st["grpcSettings"] = {"serviceName": m.get("service_name") or "", "multiMode": m.get("mode") == "multi"}
    elif net == "httpupgrade":
        st["httpupgradeSettings"] = {"path": path, "host": host}
    elif net == "xhttp":
        st["xhttpSettings"] = {"path": path, "host": host, "mode": m.get("mode") or "auto"}
    elif net == "h2":
        raise ValueError("Xray removed the HTTP/2 (h2) transport; switch the core to sing-box or use xhttp")
    else:
        raise ValueError(f"The {net} transport isn't supported")
    return st


def xray_outbound(node: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """Xray outbound for any node shape."""
    if node_kind(node) == "xray":  # pasted Xray JSON: keep every field
        out = {k: v for k, v in node.items() if k not in ("raw", "remark", "name")}
        out["tag"] = tag
        return out
    m = to_model(node)
    if m["type"] == "shadowsocks":
        if m.get("plugin"):
            raise ValueError("Shadowsocks plugins only work on sing-box; switch the core to sing-box")
        return {"protocol": "shadowsocks", "tag": tag, "settings": {"servers": [{
            "address": m["server"], "port": m["server_port"], "method": m["method"], "password": m["password"]}]}}
    if m["type"] in ("vless", "vmess"):
        user: Dict[str, Any] = {"id": m["uuid"]}
        if m["type"] == "vless":
            user["encryption"] = "none"
            if m.get("flow"):
                user["flow"] = m["flow"]
        else:
            user.update({"alterId": m.get("alter_id", 0), "security": m.get("vmess_security") or "auto"})
        settings = {"vnext": [{"address": m["server"], "port": m["server_port"], "users": [user]}]}
    else:
        settings = {"servers": [{"address": m["server"], "port": m["server_port"], "password": m["password"]}]}
    return {"protocol": m["type"], "tag": tag, "settings": settings, "streamSettings": _xray_stream(m)}


# --- Minimal config for latency test: single node, HTTP inbound on temp port, all traffic via proxy ---
LATENCY_TEST_HTTP_PORT = 19099


def build_minimal_singbox_config(node: Dict[str, Any], http_port: int = LATENCY_TEST_HTTP_PORT) -> Dict[str, Any]:
    """Minimal sing-box config with one node and one HTTP inbound, for the real latency test."""
    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "local", "address": "223.5.5.5", "detour": "direct"},
                {"tag": "remote", "address": "https://cloudflare-dns.com/dns-query", "detour": "proxy", "address_resolver": "local"},
            ],
            # The node's own hostname must resolve outside the node, or the lookup loops through it
            "rules": [{"outbound": "any", "server": "local"}],
            "final": "remote",
            "independent_cache": True,
        },
        "inbounds": [{"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": http_port}],
        "outbounds": [singbox_outbound(node, "proxy"), {"type": "direct", "tag": "direct"}],
        "route": {"rules": [], "final": "proxy"},
    }


def build_minimal_xray_config(node: Dict[str, Any], http_port: int = LATENCY_TEST_HTTP_PORT) -> Dict[str, Any]:
    """Minimal Xray config with one node and one HTTP inbound, for the real latency test."""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": http_port, "protocol": "http", "settings": {}, "tag": "http-in"}],
        "outbounds": [xray_outbound(node, "proxy"), {"protocol": "freedom", "tag": "direct"}],
        "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]},
    }


# --- All nodes in one config: switch without restarts, pick the fastest, pool connections ---
NODE_TAG_PREFIX = "node-"
MULTIPLEX_PROTOCOLS = ("h2mux", "smux", "yamux")


def node_tag(node_id: int) -> str:
    return f"{NODE_TAG_PREFIX}{node_id}"


def _is_vision(outbound: Dict[str, Any]) -> bool:
    return "vision" in str(outbound.get("flow") or "") or any(
        "vision" in str(u.get("flow") or "")
        for vnext in (outbound.get("settings") or {}).get("vnext", [])
        for u in vnext.get("users", [])
    )


def _singbox_node_outbound(node: Dict[str, Any], tag: str, multiplex: str, tcp_fast_open: bool) -> Dict[str, Any]:
    out = singbox_outbound(node, tag)
    # Vision (XTLS flow) cannot be multiplexed
    if multiplex in MULTIPLEX_PROTOCOLS and not _is_vision(out):
        out["multiplex"] = {"enabled": True, "protocol": multiplex, "max_connections": 4, "min_streams": 4}
    if tcp_fast_open:
        out["tcp_fast_open"] = True
    return out


def _xray_node_outbound(node: Dict[str, Any], tag: str, multiplex: str, tcp_fast_open: bool) -> Dict[str, Any]:
    out = xray_outbound(node, tag)
    if multiplex in MULTIPLEX_PROTOCOLS and not _is_vision(out):
        out["mux"] = {"enabled": True, "concurrency": 8, "xudpConcurrency": 16, "xudpProxyUDP443": "reject"}
    if tcp_fast_open:
        out.setdefault("streamSettings", {}).setdefault("sockopt", {})["tcpFastOpen"] = True
    return out


def apply_node_outbounds(
    config: Dict[str, Any],
    core_type: str,
    nodes: List[Dict[str, Any]],
    mode: str,
    active_id: Optional[int],
    test_url: str,
    tcp_fast_open: bool = False,
) -> Dict[str, Any]:
    """Replace the node outbounds and the "proxy" group in config. Mutates and returns config.

    nodes: [{"id", "parsed", "multiplex"}]. mode: "manual" (active_id is used) or "auto" (fastest node).
    sing-box: every node is an outbound; "proxy" is a selector (manual, switchable live through the
    Clash API) or a urltest (auto). Xray: manual keeps a single "proxy" outbound (switching restarts);
    auto adds every node and a leastPing balancer tagged "proxy" fed by the observatory.
    With no usable node, no "proxy" exists, so the full-tunnel ports stay closed.
    """
    outbounds = [
        o for o in config.get("outbounds", [])
        if not (isinstance(o, dict) and (o.get("tag") == "proxy" or str(o.get("tag", "")).startswith(NODE_TAG_PREFIX)))
    ]
    if core_type == "xray":
        routing = config.setdefault("routing", {})
        routing["balancers"] = [b for b in routing.get("balancers", []) if b.get("tag") != "proxy"]
        if not routing["balancers"]:
            routing.pop("balancers")
        config.pop("observatory", None)

    def usable(build, items, tag_for):
        """Build outbounds, skipping nodes this core can't use (the active node must work)."""
        built = []
        for n in items:
            try:
                built.append(build(n["parsed"], tag_for(n), n["multiplex"], tcp_fast_open))
            except ValueError:
                if mode != "auto" and n["id"] == active_id:
                    raise
        return built

    if mode == "auto":
        chosen = nodes
    else:
        chosen = [n for n in nodes if n["id"] == active_id]

    if chosen and core_type == "xray":
        if mode == "auto":
            outbounds += usable(_xray_node_outbound, chosen, lambda n: node_tag(n["id"]))
            routing["balancers"] = routing.get("balancers", []) + [{
                "tag": "proxy",
                "selector": [NODE_TAG_PREFIX],
                "strategy": {"type": "leastPing"},
                "fallbackTag": node_tag(chosen[0]["id"]),
            }]
            config["observatory"] = {
                "subjectSelector": [NODE_TAG_PREFIX],
                "probeUrl": test_url,
                "probeInterval": "1m",
                "enableConcurrency": True,
            }
        else:
            outbounds += usable(_xray_node_outbound, chosen, lambda n: "proxy")
    elif chosen:
        if mode == "auto":
            node_outs = usable(_singbox_node_outbound, chosen, lambda n: node_tag(n["id"]))
            tags = [o["tag"] for o in node_outs]
            group = {
                "type": "urltest",
                "tag": "proxy",
                "outbounds": tags,
                "url": test_url,
                "interval": "1m",
                "tolerance": 50,
                "idle_timeout": "30m",
                "interrupt_exist_connections": False,
            }
        else:
            # Selector holds every node so "Use" can switch live without a restart
            node_outs = usable(_singbox_node_outbound, nodes, lambda n: node_tag(n["id"]))
            tags = [o["tag"] for o in node_outs]
            group = {
                "type": "selector",
                "tag": "proxy",
                "outbounds": tags,
                "default": node_tag(active_id),
                "interrupt_exist_connections": False,
            }
        if tags:
            outbounds = [group] + node_outs + outbounds
    config["outbounds"] = outbounds
    return config
