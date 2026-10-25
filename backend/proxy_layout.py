"""Ports from env, the proxy inbound layout and the DNS rules it depends on, shared by sing-box and Xray.

Four proxy inbounds, each on its own port:
  http-hybrid / socks-hybrid  -> follow the Domains rules (unmatched traffic goes direct)
  http-full   / socks-full    -> everything goes through the selected node (Domains rules ignored)

Env is the single source of truth for ports. A proxy port set to "0" or "" is disabled.
"""
import os
from typing import Any, Dict, List, Optional


def _env_port(name: str, default: int) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw in ("", "0"):
        return None
    try:
        port = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a port number, got {raw!r}")
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{name} must be between 1 and 65535, got {port}")
    return port


WEB_PORT = _env_port("CONDUIT_WEB_PORT", 7782)
API_PORT = _env_port("CONDUIT_API_PORT", 8000)
HYBRID_HTTP_PORT = _env_port("CONDUIT_HYBRID_HTTP_PORT", 8080)
FULL_HTTP_PORT = _env_port("CONDUIT_FULL_HTTP_PORT", 8081)
HYBRID_SOCKS_PORT = _env_port("CONDUIT_HYBRID_SOCKS_PORT", 1080)
FULL_SOCKS_PORT = _env_port("CONDUIT_FULL_SOCKS_PORT", 1081)
XRAY_API_PORT = _env_port("CONDUIT_XRAY_API_PORT", 10085) or 10085

CLASH_API_PORT = 9092  # sing-box Clash API on loopback: live node switching and traffic stats
# Internal ports used elsewhere in the backend; listed here only to catch collisions.
_INTERNAL_PORTS = {"sing-box Clash API": CLASH_API_PORT, "latency test core": 19099}

HTTP_HYBRID_TAG = "http-hybrid"
HTTP_FULL_TAG = "http-full"
SOCKS_HYBRID_TAG = "socks-hybrid"
SOCKS_FULL_TAG = "socks-full"
FULL_TAGS = [HTTP_FULL_TAG, SOCKS_FULL_TAG]
PROXY_TAGS = [HTTP_HYBRID_TAG, HTTP_FULL_TAG, SOCKS_HYBRID_TAG, SOCKS_FULL_TAG]

# (tag, protocol, port)
_PROXY_INBOUNDS = [
    (HTTP_HYBRID_TAG, "http", HYBRID_HTTP_PORT),
    (HTTP_FULL_TAG, "http", FULL_HTTP_PORT),
    (SOCKS_HYBRID_TAG, "socks", HYBRID_SOCKS_PORT),
    (SOCKS_FULL_TAG, "socks", FULL_SOCKS_PORT),
]


def _check_port_collisions() -> None:
    used: Dict[int, str] = {}
    named = {
        "CONDUIT_WEB_PORT": WEB_PORT,
        "CONDUIT_API_PORT": API_PORT,
        "CONDUIT_HYBRID_HTTP_PORT": HYBRID_HTTP_PORT,
        "CONDUIT_FULL_HTTP_PORT": FULL_HTTP_PORT,
        "CONDUIT_HYBRID_SOCKS_PORT": HYBRID_SOCKS_PORT,
        "CONDUIT_FULL_SOCKS_PORT": FULL_SOCKS_PORT,
        "CONDUIT_XRAY_API_PORT": XRAY_API_PORT,
        **_INTERNAL_PORTS,
    }
    for name, port in named.items():
        if port is None:
            continue
        if port in used:
            raise RuntimeError(f"Port {port} is used by both {used[port]} and {name}")
        used[port] = name


_check_port_collisions()


def proxy_ports() -> Dict[str, Optional[int]]:
    """Ports exposed to the UI (None = disabled)."""
    return {
        "web_port": WEB_PORT,
        "hybrid_http_port": HYBRID_HTTP_PORT,
        "full_http_port": FULL_HTTP_PORT,
        "hybrid_socks_port": HYBRID_SOCKS_PORT,
        "full_socks_port": FULL_SOCKS_PORT,
    }


def _has_proxy_outbound(config: Dict[str, Any]) -> bool:
    """True when "proxy" exists: an outbound/group, or (Xray auto mode) a balancer."""
    balancers = (config.get("routing") or {}).get("balancers") or []
    return any(ob.get("tag") == "proxy" for ob in config.get("outbounds", []) + balancers if isinstance(ob, dict))


def _enabled_inbounds(include_full: bool):
    for tag, protocol, port in _PROXY_INBOUNDS:
        if port is None:
            continue
        if tag in FULL_TAGS and not include_full:
            continue
        yield tag, protocol, port


def _singbox_inbounds(include_full: bool, username: str, password: str) -> List[Dict[str, Any]]:
    inbounds = []
    for tag, protocol, port in _enabled_inbounds(include_full):
        inbound: Dict[str, Any] = {
            "type": protocol,
            "tag": tag,
            "listen": "0.0.0.0",
            "listen_port": port,
        }
        if tag not in FULL_TAGS:
            # Hybrid routing needs the domain (SNI/Host) when a client connects by IP. Full-tunnel ports route
            # everything to the node anyway, so they skip sniffing; the short timeout limits the wait for
            # server-first protocols (SSH, SMTP) that never send a first packet.
            inbound.update({"sniff": True, "sniff_override_destination": True, "sniff_timeout": "50ms"})
        if username:
            inbound["users"] = [{"username": username, "password": password}]
        inbounds.append(inbound)
    return inbounds


def _xray_inbounds(include_full: bool, username: str, password: str, with_api: bool) -> List[Dict[str, Any]]:
    inbounds: List[Dict[str, Any]] = []
    if with_api:
        inbounds.append({
            "listen": "127.0.0.1",
            "port": XRAY_API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
            "tag": "api",
        })
    for tag, protocol, port in _enabled_inbounds(include_full):
        settings: Dict[str, Any] = {}
        if protocol == "socks":
            settings["udp"] = True
        if username:
            # Xray HTTP and SOCKS inbounds take credentials as "accounts" of {user, pass}
            settings["accounts"] = [{"user": username, "pass": password}]
            if protocol == "socks":
                settings["auth"] = "password"
        inbounds.append({
            "tag": tag,
            "listen": "0.0.0.0",
            "port": port,
            "protocol": protocol,
            "settings": settings,
            "sniffing": {"enabled": tag not in FULL_TAGS, "destOverride": ["http", "tls"], "routeOnly": False},
        })
    return inbounds


def _is_full_tunnel_rule(rule: Dict[str, Any]) -> bool:
    tags = rule.get("inbound") or rule.get("inboundTag") or []
    return isinstance(tags, list) and bool(tags) and set(tags) <= set(FULL_TAGS)


def _full_tunnel_rule(core_type: str, tags: List[str]) -> Dict[str, Any]:
    if core_type == "xray":
        return {"type": "field", "inboundTag": tags, "outboundTag": "proxy"}
    return {"action": "route", "inbound": tags, "outbound": "proxy"}


def _ensure_node_server_dns(config: Dict[str, Any]) -> None:
    """sing-box: resolve outbound server hostnames (the node's own address) with a non-proxied DNS server.

    Without this, the node's hostname is looked up via the DNS server that itself detours through
    the node, which fails with "DNS query loopback". A user-defined `outbound` DNS rule is kept as-is.
    """
    dns = config.get("dns")
    if not isinstance(dns, dict):
        return
    rules = dns.setdefault("rules", [])
    if any(isinstance(r, dict) and "outbound" in r for r in rules):
        return
    server = next(
        (s.get("tag") for s in dns.get("servers", []) if isinstance(s, dict) and s.get("tag") and s.get("detour") != "proxy"),
        None,
    )
    if server:
        rules.insert(0, {"outbound": "any", "server": server})


def _use_balancer_for_proxy(rules: List[Dict[str, Any]], use_balancer: bool) -> None:
    """Xray: rules reach "proxy" through outboundTag, or through balancerTag in auto mode."""
    src, dst = ("outboundTag", "balancerTag") if use_balancer else ("balancerTag", "outboundTag")
    for rule in rules:
        if rule.get(src) == "proxy":
            rule[dst] = rule.pop(src)


def apply_proxy_layout(
    config: Dict[str, Any],
    core_type: str,
    proxy_username: str = "",
    proxy_password: str = "",
    verbose_logs: bool = False,
) -> Dict[str, Any]:
    """Rewrite inbounds from env ports and keep the full-tunnel rule first. Mutates and returns config.

    Full-tunnel inbounds are only added when a "proxy" outbound exists, so they never fall back to direct.
    Logging is "warn" unless verbose_logs: "info" logs a line per connection, which costs CPU under load.
    """
    username = (proxy_username or "").strip()
    password = (proxy_password or "") if username else ""
    include_full = _has_proxy_outbound(config)
    full_tags = [tag for tag, _, _ in _enabled_inbounds(include_full) if tag in FULL_TAGS]

    if core_type == "xray":
        config["inbounds"] = _xray_inbounds(include_full, username, password, with_api="api" in config)
        config.setdefault("log", {})["loglevel"] = "info" if verbose_logs else "warning"
        rules_key = "routing"
    else:
        config["inbounds"] = _singbox_inbounds(include_full, username, password)
        _ensure_node_server_dns(config)
        config["log"] = {"level": "info" if verbose_logs else "warn", "timestamp": True}
        config.setdefault("experimental", {})["clash_api"] = {"external_controller": f"127.0.0.1:{CLASH_API_PORT}"}
        rules_key = "route"

    route = config.setdefault(rules_key, {})
    rules = [r for r in route.get("rules", []) if not _is_full_tunnel_rule(r)]
    if full_tags:
        # Xray's api rule must stay first; the full-tunnel rule goes right after it.
        insert_at = 1 if rules and rules[0].get("inboundTag") == ["api"] else 0
        rules.insert(insert_at, _full_tunnel_rule(core_type, full_tags))
    if core_type == "xray":
        for rule in rules:
            # Older Conduit wrote Xray rules with sing-box's "outbound" key, which Xray ignores
            if "outbound" in rule and "outboundTag" not in rule and "balancerTag" not in rule:
                rule["outboundTag"] = rule.pop("outbound")
            rule.setdefault("type", "field")
        balancers = route.get("balancers") or []
        _use_balancer_for_proxy(rules, any(b.get("tag") == "proxy" for b in balancers))
    route["rules"] = rules
    return config
