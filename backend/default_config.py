"""Default configuration generators for sing-box and Xray."""
from typing import Dict, Any


def get_default_singbox_config() -> Dict[str, Any]:
    """Generate default sing-box configuration."""
    return {
        "log": {
            "level": "info",
            "timestamp": True
        },
        "dns": {
            "servers": [
                {
                    "address": "8.8.8.8",
                    "tag": "local",
                    "detour": "direct",
                    "strategy": "prefer_ipv4"
                },
                {
                    "address": "https://1.1.1.1/dns-query",
                    "tag": "remote",
                    "detour": "proxy",
                    "address_resolver": "local"
                }
            ],
            "rules": [],
            "final": "remote",
            "independent_cache": True
        },
        "inbounds": [
            {
                "type": "http",
                "tag": "http-in",
                "listen": "0.0.0.0",
                "listen_port": 8080,
                "sniff": True,
                "sniff_override_destination": True
            },
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "0.0.0.0",
                "listen_port": 1080,
                "sniff": True,
                "sniff_override_destination": True
            }
        ],
        "outbounds": [
            {
                "type": "direct",
                "tag": "direct"
            },
            {
                "type": "block",
                "tag": "block"
            }
        ],
        "route": {
            "rules": [],
            "final": "direct",
            "auto_detect_interface": True
        }
    }


def get_default_xray_config() -> Dict[str, Any]:
    """Generate default xray configuration."""
    return {
        "log": {
            "loglevel": "warning"
        },
        "dns": {
            "servers": [
                {
                    "address": "8.8.8.8",
                    "tag": "local"
                },
                {
                    "address": "https://1.1.1.1/dns-query",
                    "tag": "remote"
                }
            ],
            "final": "remote"
        },
        "inbounds": [
            {
                "tag": "http-in",
                "port": 8080,
                "listen": "0.0.0.0",
                "protocol": "http",
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"]
                }
            },
            {
                "tag": "socks-in",
                "port": 1080,
                "listen": "0.0.0.0",
                "protocol": "socks",
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"]
                }
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct"
            },
            {
                "protocol": "blackhole",
                "tag": "block"
            }
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [],
            "final": "direct"
        }
    }


def get_default_config(core_type: str) -> Dict[str, Any]:
    """Get default config for the specified core type."""
    if core_type == "xray":
        return get_default_xray_config()
    return get_default_singbox_config()
