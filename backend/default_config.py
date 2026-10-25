"""Default configuration generators for sing-box and Xray."""
from typing import Dict, Any

from proxy_layout import apply_proxy_layout


def get_default_singbox_config() -> Dict[str, Any]:
    """Generate default sing-box configuration."""
    return apply_proxy_layout({
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
        "inbounds": [],
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
    }, "sing-box")


def get_default_xray_config() -> Dict[str, Any]:
    """Generate default xray configuration."""
    return apply_proxy_layout({
        "log": {
            "loglevel": "warning"
        },
        # Stats API (loopback inbound added by the layout) so the Dashboard can show traffic
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService"]},
        "policy": {"system": {"statsInboundUplink": True, "statsInboundDownlink": True}},
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
        "inbounds": [],
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
            # Unmatched traffic uses the first outbound ("direct"); Xray has no "final" key
            "rules": [{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}]
        }
    }, "xray")


def get_default_config(core_type: str) -> Dict[str, Any]:
    """Get default config for the specified core type."""
    if core_type == "xray":
        return get_default_xray_config()
    return get_default_singbox_config()
