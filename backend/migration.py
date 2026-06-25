"""One-time migration from database-based config to file-based config."""
import json
from typing import Dict, Any
from database import db_connection
from default_config import get_default_singbox_config, get_default_xray_config
from config_file_manager import ConfigFileManager
from core_manager import get_config_path, get_xray_config_path


async def migrate_db_to_config() -> bool:
    """
    Migrate existing database config to config file (one-time).
    Returns True if migration was performed, False if already done.
    """
    # Check if migration already done
    migration_flag = await _get_db_setting("config_migration_done")
    if migration_flag:
        return False

    # Get current settings
    settings = await get_all_settings()
    core_type = settings.get("core_type", "sing-box")

    # Get config manager
    config_path = get_xray_config_path() if core_type == "xray" else get_config_path()
    manager = ConfigFileManager(config_path)

    # Try to read existing config, or create default
    try:
        config = manager.read_config()
    except FileNotFoundError:
        # Create default config
        config = get_default_xray_config() if core_type == "xray" else get_default_singbox_config()

    # Migrate domains from database to config
    domains = await _get_proxy_domains()
    if domains:
        rules_key = "route" if core_type == "sing-box" else "routing"
        if rules_key not in config:
            config[rules_key] = {"rules": [], "final": "direct"}
        if "rules" not in config[rules_key]:
            config[rules_key]["rules"] = []

        # Add existing domains to config
        for domain_type, value, outbound in domains:
            rule = _domain_to_routing_rule(domain_type, value, outbound, core_type)
            config[rules_key]["rules"].append(rule)

    # Write migrated config to file
    manager.write_config(config)

    # Mark migration as complete
    await _update_db_setting("config_migration_done", "true")

    return True


async def _get_db_setting(key: str) -> str | None:
    """Get a setting value from database."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def _update_db_setting(key: str, value: str) -> None:
    """Update a setting value in database."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await conn.commit()


async def get_all_settings() -> Dict[str, str]:
    """Get all settings from database."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
    return {r[0]: r[1] for r in rows}


async def _get_proxy_domains() -> list:
    """Get all proxy domains from database."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT type, value, outbound FROM proxy_domains ORDER BY id")
        rows = await cursor.fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _domain_to_routing_rule(domain_type: str, value: str, outbound: str, core_type: str) -> Dict[str, Any]:
    """Convert a domain database entry to a routing rule."""
    outbound = outbound or "proxy"

    if core_type == "sing-box":
        # Sing-box format
        if domain_type == "exact":
            return {
                "action": "route",
                "outbound": outbound,
                "domain": [value]
            }
        elif domain_type == "domain_suffix":
            # Strip leading dot if present
            clean_value = value.lstrip(".")
            return {
                "action": "route",
                "outbound": outbound,
                "domain": [clean_value],
                "domain_suffix": [f".{clean_value}"]
            }
        elif domain_type == "contains":
            return {
                "action": "route",
                "outbound": outbound,
                "domain_keyword": [value]
            }
        elif domain_type == "regex":
            return {
                "action": "route",
                "outbound": outbound,
                "domain_regex": [value]
            }
        else:
            # Legacy types
            if domain_type == "domain":
                return {
                    "action": "route",
                    "outbound": outbound,
                    "domain": [value]
                }
            elif domain_type == "suffix":
                clean_value = value.lstrip(".")
                return {
                    "action": "route",
                    "outbound": outbound,
                    "domain_suffix": [f".{clean_value}"]
                }
            elif domain_type == "keyword":
                return {
                    "action": "route",
                    "outbound": outbound,
                    "domain_keyword": [value]
                }
            # Default to exact
            return {
                "action": "route",
                "outbound": outbound,
                "domain": [value]
            }
    else:
        # Xray format
        if domain_type == "exact":
            return {
                "type": "field",
                "domain": [f"full:{value}"],
                "outbound": outbound
            }
        elif domain_type == "domain_suffix":
            clean_value = value.lstrip(".")
            return {
                "type": "field",
                "domain": [f"domain:{clean_value}"],
                "outbound": outbound
            }
        elif domain_type == "contains":
            return {
                "type": "field",
                "domain": [f"keyword:{value}"],
                "outbound": outbound
            }
        elif domain_type == "regex":
            return {
                "type": "field",
                "domain": [f"regexp:{value}"],
                "outbound": outbound
            }
        else:
            # Legacy types
            if domain_type == "domain":
                return {
                    "type": "field",
                    "domain": [f"full:{value}"],
                    "outbound": outbound
                }
            elif domain_type == "suffix":
                clean_value = value.lstrip(".")
                return {
                    "type": "field",
                    "domain": [f"domain:{clean_value}"],
                    "outbound": outbound
                }
            elif domain_type == "keyword":
                return {
                    "type": "field",
                    "domain": [f"keyword:{value}"],
                    "outbound": outbound
                }
            # Default to exact
            return {
                "type": "field",
                "domain": [f"full:{value}"],
                "outbound": outbound
            }
