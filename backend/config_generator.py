"""Generate sing-box JSON config from selected node and proxy_domains."""
import json
import os
from typing import Dict, Any, List

# When set (e.g. SINGBOX_CLASH_API=1), add experimental Clash API so Dashboard can show upload/download for sing-box
SINGBOX_CLASH_API_ENV = "SINGBOX_CLASH_API"
SINGBOX_CLASH_API_PORT = 9092


def _first_param(params: Dict[str, Any], key: str, default: str = "") -> str:
    """Get first value from params (query string style: lists or single value)."""
    v = params.get(key)
    if v is None:
        return default
    if isinstance(v, list) and v:
        return str(v[0]).strip() if v[0] is not None else default
    return str(v).strip() if v is not None else default


def _apply_params_to_node(node: Dict[str, Any]) -> None:
    """Copy transport/tls from node['params'] (v2ray query style) to top-level for _build_transport/_build_tls."""
    params = node.get("params") or {}
    if not params:
        return
    # type / headerType -> net (v2ray: headerType=http = HTTP transport in sing-box, or ws in Xray/tcp disguise)
    net = _first_param(params, "type") or _first_param(params, "network")
    if _first_param(params, "headerType").lower() == "http":
        net = "http"  # sing-box uses transport type "http" with host; Xray uses tcp+http disguise
    if net:
        node["net"] = net.lower()
    path = _first_param(params, "path", "/")
    if path:
        node["path"] = path
    host = _first_param(params, "host") or _first_param(params, "sni")
    if host:
        node["host"] = host
    security = _first_param(params, "security")
    if security:
        node["security"] = security.lower()
    sni = _first_param(params, "sni")
    if sni:
        node["sni"] = sni
    header_type = _first_param(params, "headerType")
    if header_type:
        node["headerType"] = header_type
    # TLS from security
    if node.get("security") == "tls" or node.get("security") == "reality":
        node["tls"] = "tls"


def _build_tls(node: Dict[str, Any], sni: str = None) -> Dict[str, Any]:
    """Build TLS block if TLS is used."""
    server = node.get("server") or node.get("add")
    sni = sni or node.get("sni") or node.get("host") or server
    if node.get("tls") in ("tls", "1", True) or node.get("security") == "tls":
        return {"enabled": True, "server_name": sni}
    return {"enabled": False}


def _build_transport(node: Dict[str, Any]) -> Dict[str, Any]:
    """Build transport (ws, grpc, etc.) from node params."""
    # Prefer net (set from params); for VLESS/VMess type is protocol name so don't use it for transport
    net = (node.get("net") or "tcp").lower()
    if net == "tcp" and node.get("type") and node.get("type") not in ("vless", "vmess", "trojan", "shadowsocks"):
        net = (node.get("type") or "tcp").lower()
    if net == "ws":
        headers = dict(node.get("headers") or {})
        if node.get("host") and "Host" not in headers:
            headers["Host"] = node["host"]
        return {
            "type": "ws",
            "path": node.get("path") or "/",
            "headers": headers,
        }
    if net == "grpc":
        return {
            "type": "grpc",
            "service_name": node.get("serviceName") or node.get("path") or "grpc",
        }
    if net == "http":
        return {
            "type": "http",
            "path": node.get("path") or "/",
            "host": [node.get("host") or node.get("add") or ""] if node.get("host") else [],
        }
    if net == "h2":
        return {
            "type": "http",
            "path": node.get("path") or "/",
            "host": [node.get("host") or node.get("add") or ""] if node.get("host") else [],
        }
    return {}


def parsed_to_singbox_outbound(node: Dict[str, Any], tag: str = "proxy") -> Dict[str, Any]:
    """Convert parsed node (from subscription or manual) to sing-box outbound."""
    _apply_params_to_node(node)
    t = node.get("type")
    server = node.get("server") or node.get("add")
    port = int(node.get("server_port") or node.get("port") or 443)

    if t == "vless":
        out = {
            "type": "vless",
            "tag": tag,
            "server": server,
            "server_port": port,
            "uuid": node.get("uuid", ""),
            "network": "tcp",
            "packet_encoding": "xudp",
        }
        flow = (node.get("params") or {}).get("flow")
        if flow:
            flow_val = flow[0] if isinstance(flow, list) and flow else flow
            if flow_val:
                out["flow"] = flow_val
        tls = _build_tls(node)
        if tls.get("enabled"):
            out["tls"] = tls
        transport = _build_transport(node)
        if transport:
            out["transport"] = transport
        return out

    if t == "vmess":
        out = {
            "type": "vmess",
            "tag": tag,
            "server": server,
            "server_port": port,
            "uuid": node.get("id", ""),
            "security": "auto",
            "alter_id": int(node.get("aid") or 0),
            "network": (node.get("net") or "tcp").lower(),
        }
        tls = _build_tls(node)
        if tls.get("enabled"):
            out["tls"] = tls
        transport = _build_transport(node)
        if transport:
            out["transport"] = transport
        return out

    if t == "trojan":
        out = {
            "type": "trojan",
            "tag": tag,
            "server": server,
            "server_port": port,
            "password": node.get("password", ""),
            "network": "tcp",
        }
        tls = _build_tls(node)
        if tls.get("enabled"):
            out["tls"] = tls
        transport = _build_transport(node)
        if transport:
            out["transport"] = transport
        return out

    if t == "shadowsocks":
        out = {
            "type": "shadowsocks",
            "tag": tag,
            "server": server,
            "server_port": port,
            "method": node.get("method", "aes-256-gcm"),
            "password": node.get("password", ""),
        }
        return out

    return {}


def _is_singbox_outbound(node: Dict[str, Any]) -> bool:
    """True if node looks like a sing-box outbound (has type + server + port)."""
    t = node.get("type")
    if t not in ("vless", "vmess", "trojan", "shadowsocks"):
        return False
    server = node.get("server") or node.get("add")
    port = node.get("server_port") or node.get("port")
    return bool(server and port is not None)


# Keys that are not part of sing-box outbound schema (v2ray/share-link/app fields)
_SINGBOX_OUTBOUND_STRIP = frozenset({
    "raw", "remark", "name", "params", "latency_ms", "last_check",
    "add", "ps",  # v2ray/share-link; "id" is used by vmess, "port" copied to server_port
})


def _normalize_singbox_outbound(node: Dict[str, Any], tag: str = "proxy") -> Dict[str, Any]:
    """Use a sing-box outbound as-is, ensuring tag and server_port (sing-box uses server_port)."""
    out = {k: v for k, v in node.items() if k not in _SINGBOX_OUTBOUND_STRIP}
    out["tag"] = tag
    if "server_port" not in out and node.get("port") is not None:
        out["server_port"] = node["port"]
    out.pop("port", None)  # sing-box only accepts server_port
    return out


def build_singbox_config(
    outbound_node: Dict[str, Any],
    proxy_domains: List[Dict[str, Any]],
    http_port: int = 8080,
    socks_port: int = 1080,
    proxy_username: str = "",
    proxy_password: str = "",
) -> Dict[str, Any]:
    """
    Build full sing-box config: inbounds (http + socks), outbounds (proxy + direct), route rules.
    proxy_domains: list of {"type": "domain"|"suffix"|"keyword"|"regex", "value": "..."}
    When proxy_username and proxy_password are both non-empty, HTTP and SOCKS inbounds require auth.
    """
    # If node has v2ray-style params, always use parsed path so transport/tls are built from params
    if outbound_node.get("params") and _is_singbox_outbound(outbound_node):
        proxy_out = parsed_to_singbox_outbound(outbound_node, tag="proxy")
    elif _is_singbox_outbound(outbound_node):
        proxy_out = _normalize_singbox_outbound(outbound_node, tag="proxy")
    else:
        proxy_out = parsed_to_singbox_outbound(outbound_node, tag="proxy")
    if not proxy_out:
        raise ValueError("Unsupported node type or invalid node. Use a share link (vmess://, vless://, ...) or a sing-box outbound JSON with type, server, server_port.")

    rules = []
    for d in proxy_domains:
        rule_type = d.get("type", "domain")
        value = d.get("value", "").strip()
        value_lower = value.lower()
        outbound_tag = d.get("outbound", "proxy")
        if not value:
            continue
        rule = {"action": "route", "outbound": outbound_tag}
        if rule_type == "exact":
            rule["domain"] = [value_lower]
        elif rule_type == "domain_suffix":
            # Domain + subdomains: match apex domain exactly and all subdomains via suffix
            suffix = value_lower if value_lower.startswith(".") else f".{value_lower}"
            rules.append({"action": "route", "outbound": outbound_tag, "domain": [value_lower]})
            rule["domain_suffix"] = [suffix]
        elif rule_type == "contains":
            rule["domain_keyword"] = [value_lower]
        elif rule_type == "regex":
            rule["domain_regex"] = [value]
        elif rule_type == "domain":
            rule["domain"] = [value_lower]
            rules.append({"action": "route", "outbound": outbound_tag, "domain_suffix": [f".{value_lower}"]})
        elif rule_type == "suffix":
            rule["domain_suffix"] = [value_lower if value_lower.startswith(".") else f".{value_lower}"]
        elif rule_type == "keyword":
            rule["domain_keyword"] = [value_lower]
        else:
            rule["domain_regex"] = [value]
        rules.append(rule)

    # Sniff TLS/HTTP so routing sees the domain (SNI/Host), not the resolved IP.
    listen_fields = {
        "sniff": True,
        "sniff_override_destination": True,
    }
    use_auth = bool((proxy_username or "").strip() and proxy_password is not None)
    users = [{"username": (proxy_username or "").strip(), "password": proxy_password or ""}] if use_auth else []

    # Legacy DNS format only (no "type" / "server" / hosts); compatible with sing-box < 1.12.0
    dns_servers = [
        {"tag": "local_local", "address": "223.5.5.5"},
        {
            "tag": "remote_dns",
            "address": "https://cloudflare-dns.com/dns-query",
            "detour": "proxy",
            "address_resolver": "local_local",
        },
        {
            "tag": "direct_dns",
            "address": "https://dns.alidns.com/dns-query",
            "address_resolver": "local_local",
        },
    ]
    dns_rules = [
        {"server": "direct_dns", "domain_suffix": ["alidns.com", "doh.pub", "dot.pub", "360.cn", "onedns.net"]},
    ]
    dns_block = {
        "servers": dns_servers,
        "rules": dns_rules,
        "final": "remote_dns",
        "independent_cache": True,
    }

    http_in = {
        "type": "http",
        "tag": "http-in",
        "listen": "0.0.0.0",
        "listen_port": http_port,
        **listen_fields,
    }
    if users:
        http_in["users"] = users
    socks_in = {
        "type": "socks",
        "tag": "socks-in",
        "listen": "0.0.0.0",
        "listen_port": socks_port,
        **listen_fields,
    }
    if users:
        socks_in["users"] = users
    config = {
        "log": {"level": "info", "timestamp": True},
        "dns": dns_block,
        "inbounds": [http_in, socks_in],
        "outbounds": [
            proxy_out,
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": rules,
            "final": "direct",
        },
    }
    if os.environ.get(SINGBOX_CLASH_API_ENV, "").strip().lower() in ("1", "true", "yes"):
        config["experimental"] = {
            "clash_api": {"external_controller": "127.0.0.1:%s" % SINGBOX_CLASH_API_PORT},
        }
    return config


def write_config(config: Dict[str, Any], path: str) -> None:
    """Write config JSON to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# --- Minimal config for latency test: single node, HTTP inbound on temp port, all traffic via proxy ---
LATENCY_TEST_HTTP_PORT = 19099


def build_minimal_singbox_config(outbound_node: Dict[str, Any], http_port: int = LATENCY_TEST_HTTP_PORT) -> Dict[str, Any]:
    """Build a minimal sing-box config with one node and one HTTP inbound. Used for real latency test in a separate process."""
    if outbound_node.get("params") and _is_singbox_outbound(outbound_node):
        proxy_out = parsed_to_singbox_outbound(outbound_node, tag="proxy")
    elif _is_singbox_outbound(outbound_node):
        proxy_out = _normalize_singbox_outbound(outbound_node, tag="proxy")
    else:
        proxy_out = parsed_to_singbox_outbound(outbound_node, tag="proxy")
    if not proxy_out:
        raise ValueError("Unsupported node type or invalid node.")
    listen_fields = {"sniff": True, "sniff_override_destination": True}
    dns_servers = [
        {"tag": "local_local", "address": "223.5.5.5"},
        {
            "tag": "remote_dns",
            "address": "https://cloudflare-dns.com/dns-query",
            "detour": "proxy",
            "address_resolver": "local_local",
        },
    ]
    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {"servers": dns_servers, "final": "remote_dns", "independent_cache": True},
        "inbounds": [
            {
                "type": "http",
                "tag": "http-in",
                "listen": "127.0.0.1",
                "listen_port": http_port,
                **listen_fields,
            },
        ],
        "outbounds": [proxy_out, {"type": "direct", "tag": "direct"}],
        "route": {"rules": [], "final": "proxy"},
    }


def build_minimal_xray_config(outbound_node: Dict[str, Any], http_port: int = LATENCY_TEST_HTTP_PORT) -> Dict[str, Any]:
    """Build a minimal Xray config with one node and one HTTP inbound. Used for real latency test in a separate process."""
    if _is_singbox_outbound(outbound_node):
        node = dict(outbound_node)
        node["type"] = node.get("type")
        node["server"] = node.get("server")
        node["add"] = node.get("server")
        node["port"] = node.get("server_port") or node.get("port")
        node["server_port"] = node.get("server_port") or node.get("port")
        node["uuid"] = node.get("uuid") or node.get("id")
        node["id"] = node.get("uuid") or node.get("id")
        proxy_out = _parsed_to_xray_outbound(node, tag="proxy")
    else:
        proxy_out = _parsed_to_xray_outbound(outbound_node, tag="proxy")
    if not proxy_out:
        raise ValueError("Unsupported node type or invalid node.")
    sniff = {"enabled": True, "destOverride": ["http", "tls"], "routeOnly": False}
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": http_port,
                "protocol": "http",
                "settings": {},
                "tag": "http-in",
                "sniffing": sniff,
            },
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            proxy_out,
        ],
        "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]},
    }


# --- Xray config (same inbounds: HTTP + SOCKS; routing by domain; outbound from parsed node) ---


def _xray_stream_settings(node: Dict[str, Any]) -> Dict[str, Any]:
    """Build Xray streamSettings from parsed node (network, security, ws/grpc/tcp+http/tls)."""
    net = (node.get("net") or node.get("type") or "tcp").lower()
    server = node.get("server") or node.get("add")
    sni = node.get("sni") or node.get("host") or server
    use_tls = node.get("tls") in ("tls", "1", True) or node.get("security") == "tls"
    header_type = (node.get("headerType") or "").lower()

    # Xray: type=tcp&headerType=http → TCP with HTTP disguise (tcpSettings.header.type "http")
    if header_type == "http" and (node.get("host") or node.get("path")):
        path = (node.get("path") or "/").strip() or "/"
        host = (node.get("host") or "").strip()
        stream: Dict[str, Any] = {
            "network": "tcp",
            "security": "tls" if use_tls else "none",
            "tcpSettings": {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [path],
                        "headers": {
                            "Host": [host] if host else ["localhost"],
                            "User-Agent": ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"],
                            "Accept-Encoding": ["gzip", "deflate"],
                            "Connection": ["keep-alive"],
                            "Pragma": "no-cache",
                        },
                    },
                },
            },
        }
        if use_tls and sni:
            stream["tlsSettings"] = {"serverName": sni, "allowInsecure": False}
        return stream

    # Xray network: tcp (raw), ws, grpc; http/h2 map to tcp+tls
    if net in ("http", "h2"):
        net = "tcp"
    stream = {
        "network": "tcp" if net in ("tcp", "tls") else net,
        "security": "tls" if use_tls else "none",
    }
    if use_tls and sni:
        stream["tlsSettings"] = {"serverName": sni, "allowInsecure": False}
    if net == "ws":
        path = node.get("path") or "/"
        headers = dict(node.get("headers") or {})
        if node.get("host") and "Host" not in headers:
            headers["Host"] = node["host"]
        stream["wsSettings"] = {"path": path, "headers": headers}
    if net == "grpc":
        stream["grpcSettings"] = {
            "serviceName": node.get("serviceName") or node.get("path") or "grpc",
        }
    return stream


def _parsed_to_xray_outbound(node: Dict[str, Any], tag: str = "proxy") -> Dict[str, Any] | None:
    """Convert parsed node to Xray outbound (protocol + settings + streamSettings)."""
    _apply_params_to_node(node)
    t = node.get("type")
    server = node.get("server") or node.get("add")
    port = int(node.get("server_port") or node.get("port") or 443)
    stream = _xray_stream_settings(node)

    if t == "vless":
        flow = (node.get("params") or {}).get("flow")
        flow_val = flow[0] if isinstance(flow, list) and flow else (flow or "")
        user: Dict[str, Any] = {
            "id": node.get("uuid", ""),
            "encryption": "none",
        }
        if flow_val:
            user["flow"] = flow_val
        settings: Dict[str, Any] = {
            "vnext": [
                {"address": server, "port": port, "users": [user]},
            ]
        }
        out: Dict[str, Any] = {
            "protocol": "vless",
            "tag": tag,
            "settings": settings,
            "streamSettings": stream,
            "mux": {"enabled": False, "concurrency": -1},
        }
        return out

    if t == "vmess":
        return {
            "protocol": "vmess",
            "tag": tag,
            "settings": {
                "vnext": [
                    {
                        "address": server,
                        "port": port,
                        "users": [
                            {
                                "id": node.get("id", ""),
                                "security": "auto",
                                "alterId": int(node.get("aid") or 0),
                            }
                        ],
                    }
                ]
            },
            "streamSettings": stream,
        }

    if t == "trojan":
        return {
            "protocol": "trojan",
            "tag": tag,
            "settings": {
                "servers": [{"address": server, "port": port, "password": node.get("password", "")}]
            },
            "streamSettings": stream,
        }

    if t == "shadowsocks":
        return {
            "protocol": "shadowsocks",
            "tag": tag,
            "settings": {
                "servers": [
                    {
                        "address": server,
                        "port": port,
                        "method": node.get("method", "aes-256-gcm"),
                        "password": node.get("password", ""),
                    }
                ]
            },
        }

    return None


def build_xray_config(
    outbound_node: Dict[str, Any],
    proxy_domains: List[Dict[str, Any]],
    http_port: int = 8080,
    socks_port: int = 1080,
    proxy_username: str = "",
    proxy_password: str = "",
) -> Dict[str, Any]:
    """
    Build full Xray config: inbounds (http + socks), outbounds (proxy + direct), routing rules.
    proxy_domains: list of {"type": "domain"|"suffix"|"keyword"|"regex", "value": "..."}
    When proxy_username and proxy_password are both non-empty, HTTP and SOCKS inbounds require auth.
    """
    # Support raw sing-box outbound from manual paste: convert to our parsed shape then to Xray
    if _is_singbox_outbound(outbound_node):
        node = dict(outbound_node)
        node["type"] = node.get("type")
        node["server"] = node.get("server")
        node["add"] = node.get("server")
        node["port"] = node.get("server_port") or node.get("port")
        node["server_port"] = node.get("server_port") or node.get("port")
        node["uuid"] = node.get("uuid") or node.get("id")
        node["id"] = node.get("uuid") or node.get("id")
        proxy_out = _parsed_to_xray_outbound(node, tag="proxy")
    else:
        proxy_out = _parsed_to_xray_outbound(outbound_node, tag="proxy")
    if not proxy_out:
        raise ValueError(
            "Unsupported node type or invalid node. Use a share link (vmess://, vless://, ...) or a sing-box outbound JSON."
        )

    rules = []
    for d in proxy_domains:
        rule_type = d.get("type", "domain")
        value = (d.get("value") or "").strip()
        value_lower = value.lower()
        outbound_tag = d.get("outbound", "proxy")
        if not value:
            continue
        if rule_type == "exact":
            rules.append({"type": "field", "domain": [f"full:{value_lower}"], "outboundTag": outbound_tag})
        elif rule_type == "domain_suffix":
            suffix = value_lower.lstrip(".") or value_lower
            rules.append({"type": "field", "domain": [f"domain:{suffix}"], "outboundTag": outbound_tag})
        elif rule_type == "contains":
            rules.append({"type": "field", "domain": [f"keyword:{value_lower}"], "outboundTag": outbound_tag})
        elif rule_type == "regex":
            rules.append({"type": "field", "domain": [f"regexp:{value}"], "outboundTag": outbound_tag})
        elif rule_type == "domain":
            rules.append({"type": "field", "domain": [f"domain:{value_lower}"], "outboundTag": outbound_tag})
        elif rule_type == "suffix":
            suffix = value_lower if value_lower.startswith(".") else f".{value_lower}"
            rules.append({"type": "field", "domain": [f"domain:{suffix.lstrip('.')}"], "outboundTag": outbound_tag})
        elif rule_type == "keyword":
            rules.append({"type": "field", "domain": [f"keyword:{value_lower}"], "outboundTag": outbound_tag})
        else:
            rules.append({"type": "field", "domain": [f"regexp:{value}"], "outboundTag": outbound_tag})

    # Explicit catch-all: send everything that did not match to direct (default first-outbound is direct, but this makes it explicit)
    rules.append({"type": "field", "network": "tcp,udp", "outboundTag": "direct"})

    sniff = {"enabled": True, "destOverride": ["http", "tls"], "routeOnly": False}
    use_auth = bool((proxy_username or "").strip() and proxy_password is not None)
    http_settings: Dict[str, Any] = {}
    if use_auth:
        http_settings["accounts"] = [{"user": (proxy_username or "").strip(), "pass": proxy_password or ""}]
    socks_settings: Dict[str, Any] = {"udp": True}
    if use_auth:
        # Xray SOCKS: auth "password" and accounts as array of {user, pass} (see xtls.github.io config/inbounds/socks)
        socks_settings["auth"] = "password"
        socks_settings["accounts"] = [{"user": (proxy_username or "").strip(), "pass": proxy_password or ""}]
    # API inbound for stats (StatsService); route to api outbound (Xray creates it when api is set)
    api_port = 10085
    api_rules = [{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}]
    config = {
        "log": {"loglevel": "warning"},
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService"]},
        "policy": {
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True,
            }
        },
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": api_port,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
                "tag": "api",
            },
            {
                "listen": "0.0.0.0",
                "port": http_port,
                "protocol": "http",
                "settings": http_settings,
                "tag": "http-in",
                "sniffing": sniff,
            },
            {
                "listen": "0.0.0.0",
                "port": socks_port,
                "protocol": "socks",
                "settings": socks_settings,
                "tag": "socks-in",
                "sniffing": sniff,
            },
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            proxy_out,
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {"domainStrategy": "AsIs", "rules": api_rules + rules},
    }
    return config
