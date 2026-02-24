"""Fetch and parse subscription links (base64) and share links (vmess, vless, trojan, ss)."""
import base64
import json
import re
from urllib.parse import urlparse, parse_qs, unquote
from typing import List, Dict, Any, Optional
import httpx


def _decode_base64_padding(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.standard_b64decode(s)


def parse_vmess(link: str) -> Optional[Dict[str, Any]]:
    """Parse vmess:// link (base64 json after scheme). Decoded JSON may have 'type' (header/stream); we keep protocol as 'vmess'."""
    if not link.strip().lower().startswith("vmess://"):
        return None
    try:
        b = link.strip()[8:]
        decoded = _decode_base64_padding(b).decode("utf-8", errors="replace")
        data = json.loads(decoded)
        return {**data, "type": "vmess", "raw": link}
    except Exception:
        return None


def parse_vless(link: str) -> Optional[Dict[str, Any]]:
    """Parse vless:// uuid@host:port?params#remark."""
    if not link.strip().lower().startswith("vless://"):
        return None
    try:
        rest = link.strip()[8:]
        if "#" in rest:
            rest, fragment = rest.rsplit("#", 1)
            remark = unquote(fragment)
        else:
            remark = ""
        if "?" in rest:
            netloc, qs = rest.split("?", 1)
            params = parse_qs(qs)
        else:
            netloc, params = rest, {}
        uuid = netloc.split("@")[0]
        host_port = netloc.split("@", 1)[1]
        if ":" in host_port:
            host = host_port.rsplit(":", 1)[0]
            port = int(host_port.rsplit(":", 1)[1])
        else:
            host = host_port
            port = 443
        out = {
            "type": "vless",
            "raw": link,
            "uuid": uuid,
            "server": host,
            "server_port": port,
            "remark": remark,
            "params": params,
        }
        return out
    except Exception:
        return None


def parse_trojan(link: str) -> Optional[Dict[str, Any]]:
    """Parse trojan:// password@host:port?params#remark."""
    if not link.strip().lower().startswith("trojan://"):
        return None
    try:
        rest = link.strip()[9:]
        if "#" in rest:
            rest, fragment = rest.rsplit("#", 1)
            remark = unquote(fragment)
        else:
            remark = ""
        if "?" in rest:
            netloc, qs = rest.split("?", 1)
            params = parse_qs(qs)
        else:
            netloc, params = rest, {}
        password = netloc.split("@")[0]
        host_port = netloc.split("@", 1)[1]
        if ":" in host_port:
            host = host_port.rsplit(":", 1)[0]
            port = int(host_port.rsplit(":", 1)[1])
        else:
            host = host_port
            port = 443
        return {
            "type": "trojan",
            "raw": link,
            "password": password,
            "server": host,
            "server_port": port,
            "remark": remark,
            "params": params,
        }
    except Exception:
        return None


def parse_ss(link: str) -> Optional[Dict[str, Any]]:
    """Parse ss:// [method:password]@host:port#remark or ss:// base64(method:password)@host:port#remark."""
    if not link.strip().lower().startswith("ss://"):
        return None
    try:
        rest = link.strip()[5:]
        if "#" in rest:
            rest, fragment = rest.rsplit("#", 1)
            remark = unquote(fragment)
        else:
            remark = ""
        if rest.startswith("ss://") or "://" in rest:
            return None
        if "@" in rest:
            userinfo, host_port = rest.split("@", 1)
            try:
                decoded = _decode_base64_padding(userinfo).decode("utf-8", errors="replace")
                method, password = decoded.split(":", 1)
            except Exception:
                method, _, password = userinfo.partition(":")
            if ":" in host_port:
                host = host_port.rsplit(":", 1)[0]
                port = int(host_port.rsplit(":", 1)[1])
            else:
                host = host_port
                port = 8388
            return {
                "type": "shadowsocks",
                "raw": link,
                "method": method,
                "password": password,
                "server": host,
                "server_port": port,
                "remark": remark,
            }
    except Exception:
        return None
    return None


def parse_share_link(link: str) -> Optional[Dict[str, Any]]:
    """Dispatch to vmess/vless/trojan/ss parser."""
    link = link.strip()
    if not link:
        return None
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


async def fetch_subscription(url: str, timeout: float = 15.0) -> List[Dict[str, Any]]:
    """
    Fetch subscription URL (GET), decode base64, split by newline, parse each share link.
    Returns list of parsed node dicts (with 'type', 'raw', and protocol-specific fields).
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text.strip()
    try:
        decoded = _decode_base64_padding(raw).decode("utf-8", errors="replace")
    except Exception:
        decoded = raw
    lines = [ln.strip() for ln in decoded.replace("\r", "").split("\n") if ln.strip()]
    nodes = []
    for line in lines:
        parsed = parse_share_link(line)
        if parsed:
            nodes.append(parsed)
    return nodes
