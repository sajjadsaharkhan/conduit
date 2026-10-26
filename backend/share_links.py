"""Parse share links (vmess, vless, trojan, ss) into one core-neutral node model.

Every parser returns the same keys, so config_generator can build sing-box and Xray outbounds from one
source of truth instead of translating one core's field names into the other's:

    type            vless | vmess | trojan | shadowsocks
    raw, remark     the original link and its #name
    server, server_port
    uuid            vless/vmess        password   trojan/shadowsocks
    method          shadowsocks        plugin, plugin_opts   shadowsocks (SIP003)
    alter_id, vmess_security           vmess
    flow            vless (e.g. xtls-rprx-vision)
    encryption      vless: "none" or Xray VLESS Encryption (e.g. mlkem768x25519plus.native.0rtt.<key>)
    network         tcp | ws | grpc | h2 | httpupgrade | xhttp | kcp | quic
    header_type     none | http (TCP HTTP-header obfuscation)
    path, host, service_name, mode     transport details (mode: grpc gun/multi, xhttp mode)
    xhttp_extra     dict: the link's xhttp "extra" JSON (padding, xmux, ...), passed to Xray as-is
    security        none | tls | reality
    sni, alpn (list), fingerprint, insecure (bool), pinned_cert_sha256 (Xray's replacement for insecure)
    reality_public_key, reality_short_id, reality_spider_x
"""
import base64
import binascii
import json
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

SHARE_LINK_SCHEMES = ("vmess://", "vless://", "trojan://", "ss://")
NETWORK_ALIASES = {"raw": "tcp", "http": "h2", "splithttp": "xhttp", "": "tcp"}


def is_share_link(text: str) -> bool:
    return (text or "").strip().lower().startswith(SHARE_LINK_SCHEMES)


def _b64decode(s: str) -> bytes:
    """Decode standard or URL-safe base64, with or without padding."""
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s, validate=True)


def _first(params: Dict[str, List[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        values = params.get(key)
        if values and values[0] != "":
            return values[0].strip()
    return default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _json_param(value: str) -> Dict[str, Any]:
    try:
        data = json.loads(value) if value else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _split_list(value: str) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _host_port(netloc: str, default_port: int) -> tuple:
    """host:port with IPv6 brackets removed: [2001:db8::1]:443 -> ("2001:db8::1", 443)."""
    if netloc.startswith("["):
        host, _, rest = netloc[1:].partition("]")
        port = rest.lstrip(":")
    elif netloc.count(":") == 1:
        host, port = netloc.rsplit(":", 1)
    else:
        host, port = netloc, ""
    return host, int(port) if port else default_port


def _transport_and_tls(params: Dict[str, List[str]], default_security: str = "none") -> Dict[str, Any]:
    """Shared v2rayN/Xray query parameters (vless, trojan)."""
    network = _first(params, "type", "network").lower()
    network = NETWORK_ALIASES.get(network, network)
    security = _first(params, "security", default=default_security).lower()
    if security in ("xtls", "ssl"):
        security = "tls"
    node: Dict[str, Any] = {
        "network": network,
        "header_type": _first(params, "headerType", default="none").lower(),
        "path": _first(params, "path", default="/"),
        "host": _first(params, "host"),
        "service_name": _first(params, "serviceName", "path") if network == "grpc" else "",
        "mode": _first(params, "mode"),
        "xhttp_extra": _json_param(_first(params, "extra")) if network == "xhttp" else {},
        "security": security or "none",
        "sni": _first(params, "sni", "peer"),
        "alpn": _split_list(_first(params, "alpn")),
        "fingerprint": _first(params, "fp", "fingerprint"),
        "insecure": _truthy(_first(params, "allowInsecure", "insecure", default="0")),
        "pinned_cert_sha256": _first(params, "pcs", "pinnedPeerCertSha256"),
        "reality_public_key": _first(params, "pbk", "publicKey"),
        "reality_short_id": _first(params, "sid", "shortId"),
        "reality_spider_x": _first(params, "spx", "spiderX"),
    }
    if network == "grpc" and node["path"] == node["service_name"]:
        node["path"] = "/"
    return node


def _parse_uri(link: str, scheme_len: int, default_port: int = 443):
    rest = link[scheme_len:]
    rest, _, fragment = rest.partition("#")
    netloc, _, query = rest.partition("?")
    netloc = netloc.rstrip("/")
    userinfo, _, hostport = netloc.rpartition("@")
    host, port = _host_port(hostport, default_port)
    return unquote(userinfo), host, port, parse_qs(query, keep_blank_values=True), unquote(fragment)


def parse_vless(link: str) -> Optional[Dict[str, Any]]:
    """vless://uuid@host:port?type=ws&security=tls&...#remark"""
    try:
        uuid, host, port, params, remark = _parse_uri(link.strip(), 8)
        if not uuid or not host:
            return None
        return {
            "type": "vless", "raw": link, "remark": remark, "server": host, "server_port": port,
            "uuid": uuid, "flow": _first(params, "flow"),
            "encryption": _first(params, "encryption", default="none"),
            **_transport_and_tls(params),
        }
    except (ValueError, IndexError):
        return None


def parse_trojan(link: str) -> Optional[Dict[str, Any]]:
    """trojan://password@host:port?sni=...#remark. Trojan runs over TLS unless security=none."""
    try:
        password, host, port, params, remark = _parse_uri(link.strip(), 9)
        if not password or not host:
            return None
        return {
            "type": "trojan", "raw": link, "remark": remark, "server": host, "server_port": port,
            "password": password, "flow": "",
            **_transport_and_tls(params, default_security="tls"),
        }
    except (ValueError, IndexError):
        return None


def parse_vmess(link: str) -> Optional[Dict[str, Any]]:
    """vmess://base64(JSON) in the v2rayN format (add, port, id, aid, scy, net, type, host, path, tls, sni, alpn, fp)."""
    try:
        data = json.loads(_b64decode(link.strip()[8:]).decode("utf-8", errors="replace"))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(data, dict) or not data.get("add") or not data.get("id"):
        return None
    network = NETWORK_ALIASES.get(str(data.get("net") or "").lower(), str(data.get("net") or "").lower())
    header = str(data.get("type") or "none").lower()  # header type for tcp; grpc mode (gun/multi) for grpc
    tls = str(data.get("tls") or "").lower()
    return {
        "type": "vmess", "raw": link, "remark": str(data.get("ps") or ""),
        "server": str(data["add"]).strip("[]"), "server_port": int(data.get("port") or 443),
        "uuid": str(data["id"]), "alter_id": int(data.get("aid") or 0),
        "vmess_security": str(data.get("scy") or "auto"), "flow": "",
        "network": network,
        "header_type": header if network == "tcp" else "none",
        "path": str(data.get("path") or "/") if network != "grpc" else "/",
        "host": str(data.get("host") or ""),
        "service_name": str(data.get("path") or "") if network == "grpc" else "",
        "mode": header if network == "grpc" else "",
        "security": "reality" if tls == "reality" else "tls" if tls == "tls" else "none",
        "sni": str(data.get("sni") or ""),
        "alpn": _split_list(str(data.get("alpn") or "")),
        "fingerprint": str(data.get("fp") or ""),
        "insecure": _truthy(data.get("allowInsecure") or data.get("skip-cert-verify") or "0"),
        "pinned_cert_sha256": str(data.get("pcs") or ""),
        "reality_public_key": str(data.get("pbk") or ""),
        "reality_short_id": str(data.get("sid") or ""),
        "reality_spider_x": str(data.get("spx") or ""),
    }


def parse_ss(link: str) -> Optional[Dict[str, Any]]:
    """Shadowsocks, all common forms:
    SIP002   ss://base64url(method:password)@host:port/?plugin=...#tag
             ss://method:percent-encoded-password@host:port#tag   (Shadowsocks 2022 keys)
    legacy   ss://base64(method:password@host:port)#tag
    """
    try:
        rest, _, fragment = link.strip()[5:].partition("#")
        remark = unquote(fragment)
        main, _, query = rest.partition("?")
        main = main.rstrip("/")
        if "@" not in main:  # legacy: everything base64-encoded
            main = _b64decode(unquote(main)).decode("utf-8")
        userinfo, _, hostport = main.rpartition("@")
        userinfo = unquote(userinfo)
        if ":" not in userinfo:
            userinfo = _b64decode(userinfo).decode("utf-8")
        method, _, password = userinfo.partition(":")
        host, port = _host_port(hostport, 8388)
        plugin, _, plugin_opts = _first(parse_qs(query), "plugin").partition(";")
        if not method or not host:
            return None
        return {
            "type": "shadowsocks", "raw": link, "remark": remark, "server": host, "server_port": port,
            "method": method.lower(), "password": password,
            "plugin": plugin, "plugin_opts": plugin_opts,
            "network": "tcp", "security": "none",
        }
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None


def parse_share_link(link: str) -> Optional[Dict[str, Any]]:
    """Dispatch to the vmess/vless/trojan/ss parser. None when the link can't be parsed."""
    link = (link or "").strip()
    lower = link.lower()
    if lower.startswith("vmess://"):
        return parse_vmess(link)
    if lower.startswith("vless://"):
        return parse_vless(link)
    if lower.startswith("trojan://"):
        return parse_trojan(link)
    if lower.startswith("ss://"):
        return parse_ss(link)
    return None
