"""FastAPI app: auth, settings, subscription, nodes, domains, core status. Serves frontend static."""
import asyncio
import json
import os
import subprocess
import tempfile
import time
from urllib.request import urlopen
from urllib.error import URLError
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Union
import aiosqlite
from fastapi import FastAPI, Depends, HTTPException, Header, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import hash_password, verify_password, create_access_token, decode_token
from database import init_db, db_connection
from subscription import fetch_subscription, parse_share_link
from latency import check_nodes_latency, select_best_node
from config_generator import (
    build_singbox_config,
    build_xray_config,
    build_minimal_singbox_config,
    build_minimal_xray_config,
    write_config,
    LATENCY_TEST_HTTP_PORT,
    parsed_to_singbox_outbound,
    SINGBOX_CLASH_API_PORT,
    SINGBOX_CLASH_API_ENV,
    _parsed_to_xray_outbound as parsed_to_xray_outbound,
)
from core_manager import (
    start as core_start,
    stop as core_stop,
    status as core_status,
    restart as core_restart,
    get_config_path,
    get_xray_config_path,
    get_logs as core_get_logs,
    XRAY_BIN,
    start_temp_core,
    stop_temp_core,
)
from scheduler import refresh_and_apply, start_scheduler, run_refresh_once
from latency_test import run_latency_test
from url_utils import host_from_url
from config_file_manager import ConfigFileManager
from default_config import get_default_config, get_default_singbox_config, get_default_xray_config
from migration import migrate_db_to_config


# --- Auth dependency ---
async def get_current_user(authorization: str | None = Header(None)) -> str:
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    username = decode_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


# --- Config management ---
def get_config_manager(core_type: str):
    """Get config file manager for the current core type."""
    config_path = get_xray_config_path() if core_type == "xray" else get_config_path()
    return ConfigFileManager(config_path)


# --- Pydantic models ---
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SettingUpdate(BaseModel):
    subscription_url: str | None = None
    core_type: str | None = None  # "sing-box" | "xray"
    refresh_interval_minutes: int | None = None  # 1–1440
    auto_switch_best: bool | None = None
    latency_test_domain: str | None = None  # e.g. "https://example.com"
    proxy_display_host: str | None = None  # host/IP shown in Dashboard "How to use the proxy" (display only)
    proxy_username: str | None = None  # optional auth for HTTP/SOCKS proxy (empty = no auth)
    proxy_password: str | None = None  # optional auth for HTTP/SOCKS proxy


class DomainCreate(BaseModel):
    type: str  # domain, suffix, keyword, regex, exact, domain_suffix, contains
    value: str
    outbound: str = "proxy"  # "proxy" | "direct"


class DomainBulkRequest(BaseModel):
    text: str  # newline-separated list: exact domains, *.domain.com → domain_suffix, *keyword* → contains
    outbound: str = "proxy"  # outbound applied to all imported entries: "proxy" | "direct"


class ManualConfigRequest(BaseModel):
    share_link: str | None = None  # single vmess:// or vless:// etc
    raw_json: str | None = None    # or full sing-box outbound (we merge with inbounds)


class SelectNodeRequest(BaseModel):
    raw_link: str
    node_id: int | None = None  # optional; when set, real_latency_ms is updated by id (reliable for subscription nodes)


class UpdateNodeRequest(BaseModel):
    raw_link: str


class LatencyTestRequest(BaseModel):
    url: str | None = None  # use settings latency_test_domain if omitted


# --- Lifespan: init DB, ensure admin, start scheduler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with db_connection() as cur:
        c = await cur.execute("SELECT 1 FROM users LIMIT 1")
        if await c.fetchone() is None:
            default_user = os.environ.get("ADMIN_USERNAME", "admin")
            default_pass = os.environ.get("ADMIN_PASSWORD", "admin")
            h = hash_password(default_pass)
            await cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (default_user, h),
            )
            await cur.commit()

    # Run one-time migration from DB to config file
    await migrate_db_to_config()

    start_scheduler()
    # Run first refresh after a short delay
    import asyncio
    asyncio.create_task(_delayed_refresh())
    yield
    # shutdown: stop core?
    core_stop()


async def _delayed_refresh():
    await asyncio.sleep(5)
    await run_refresh_once()


app = FastAPI(title="Conduit API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# --- Auth routes ---
@app.post("/api/auth/login")
async def login(req: LoginRequest):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT password_hash FROM users WHERE username = ?", (req.username,))
        row = await cursor.fetchone()
    if not row or not verify_password(req.password, row[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(req.username)
    return {"token": token, "username": req.username}


@app.get("/api/auth/me")
async def me(username: str = Depends(get_current_user)):
    return {"username": username}


# --- Settings ---
@app.get("/api/settings")
async def get_settings(username: str = Depends(get_current_user)):
    """Get panel settings from database. Core config is managed via /api/config."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
    settings = {r[0]: r[1] for r in rows}
    return {
        "subscription_url": settings.get("subscription_url", ""),
        "core_type": settings.get("core_type", "sing-box"),
        "last_refresh": settings.get("last_refresh", ""),
        "selected_node_raw": settings.get("selected_node_raw", ""),
        "refresh_interval_minutes": int(settings.get("refresh_interval_minutes", "1")),
        "auto_switch_best": settings.get("auto_switch_best", "true").lower() in ("true", "1", "yes"),
        "latency_test_domain": settings.get("latency_test_domain", "https://www.gstatic.com/generate_204"),
        "proxy_display_host": (settings.get("proxy_display_host") or "127.0.0.1").strip() or "127.0.0.1",
        "proxy_username": (settings.get("proxy_username") or "").strip() or "",
        "proxy_password": settings.get("proxy_password") or "",
    }


@app.put("/api/settings/password")
async def change_password(
    body: ChangePasswordRequest,
    username: str = Depends(get_current_user),
):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
    if not row or not verify_password(body.current_password, row[1]):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    new_hash = hash_password(body.new_password)
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row[0]))
        await conn.commit()
    return {"ok": True}


@app.put("/api/settings")
async def update_settings(
    body: SettingUpdate,
    username: str = Depends(get_current_user),
):
    """Update panel settings in database. Core config is managed via /api/config endpoints."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.subscription_url is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('subscription_url', ?)",
                (body.subscription_url,),
            )
        if body.core_type is not None:
            if body.core_type not in ("sing-box", "xray"):
                raise HTTPException(status_code=400, detail="core_type must be 'sing-box' or 'xray'")
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('core_type', ?)",
                (body.core_type,),
            )
        if body.refresh_interval_minutes is not None:
            v = max(1, min(1440, body.refresh_interval_minutes))
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('refresh_interval_minutes', ?)",
                (str(v),),
            )
        if body.auto_switch_best is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_switch_best', ?)",
                ("true" if body.auto_switch_best else "false",),
            )
        if body.latency_test_domain is not None:
            val = body.latency_test_domain.strip()
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('latency_test_domain', ?)",
                (val,),
            )
        if body.proxy_display_host is not None:
            val = (body.proxy_display_host or "127.0.0.1").strip() or "127.0.0.1"
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_display_host', ?)",
                (val,),
            )
        if body.proxy_username is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_username', ?)",
                (body.proxy_username.strip(),),
            )
        if body.proxy_password is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_password', ?)",
                (body.proxy_password,),
            )
        await conn.commit()
        # Reapply config so running core uses new proxy auth (rebuild config and restart)
        if body.proxy_username is not None or body.proxy_password is not None:
            selected_raw = (await _get_setting(cursor, "selected_node_raw", "") or "").strip()
            if selected_raw:
                try:
                    await _apply_node_config(selected_raw)
                except ValueError:
                    pass  # e.g. invalid node; config unchanged
    return {"ok": True}


# --- Subscription: refresh now ---
@app.post("/api/subscription/refresh")
async def subscription_refresh(username: str = Depends(get_current_user)):
    await refresh_and_apply()
    return {"ok": True}


# --- Nodes ---
@app.delete("/api/nodes/{node_id}")
async def delete_node(
    node_id: int = Path(..., gt=0, description="Node ID to delete"),
    username: str = Depends(get_current_user),
):
    """Delete a node by id. If it was the selected node, clear selection."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT raw_link FROM nodes WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Node not found")
        selected_raw = await _get_setting(cursor, "selected_node_raw", "")
        await cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        if selected_raw and selected_raw == row[0]:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
                ("",),
            )
        await conn.commit()
    return {"ok": True}


@app.put("/api/nodes/{node_id}")
async def update_node(
    node_id: int = Path(..., gt=0),
    body: UpdateNodeRequest = ...,
    username: str = Depends(get_current_user),
):
    """Update a node's share link. Re-parses and updates DB; if this node is selected, regenerates config."""
    raw_link = body.raw_link.strip()
    if not raw_link:
        raise HTTPException(status_code=400, detail="raw_link required")
    parsed = parse_share_link(raw_link)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid share link")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT raw_link, source FROM nodes WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Node not found")
        old_raw, source = row[0], row[1]
        name = parsed.get("remark") or parsed.get("name") or parsed.get("ps") or raw_link[:50]
        await cursor.execute(
            "UPDATE nodes SET raw_link = ?, parsed_json = ?, name = ? WHERE id = ?",
            (raw_link, json.dumps(parsed, ensure_ascii=False), name, node_id),
        )
        selected_raw = await _get_setting(cursor, "selected_node_raw", "")
        await conn.commit()
    if selected_raw == old_raw:
        async with db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
                (raw_link,),
            )
            await conn.commit()
        # Update the config file with the new node
        await _apply_node_config(raw_link)
    return {"ok": True}


@app.get("/api/nodes")
async def list_nodes(username: str = Depends(get_current_user)):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, source, raw_link, parsed_json, name, latency_ms, real_latency_ms, last_check FROM nodes ORDER BY latency_ms ASC, id ASC"
        )
        rows = await cursor.fetchall()
    nodes = []
    for r in rows:
        nodes.append({
            "id": r[0],
            "source": r[1],
            "raw_link": r[2],
            "name": r[4] or r[2][:50],
            "latency_ms": r[5],
            "real_latency_ms": r[6],
            "last_check": r[7],
        })
    return {"nodes": nodes}


@app.post("/api/nodes/select")
async def select_node(
    body: SelectNodeRequest,
    username: str = Depends(get_current_user),
):
    """Use a specific node (by raw_link) and regenerate config."""
    parsed = parse_share_link(body.raw_link)
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid share link")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
            (body.raw_link,),
        )
        await conn.commit()
    # Update the config file with the new node
    await _apply_node_config(body.raw_link)
    return {"ok": True}


async def _get_setting(cursor, key: str, default: str) -> str:
    await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else default


async def _apply_node_config(raw_link: str) -> None:
    """Apply node configuration by updating the config file's outbound section.
    Reads existing config (with domains, DNS, etc.) and only updates the proxy outbound."""
    if not raw_link:
        return

    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT parsed_json FROM nodes WHERE raw_link = ?", (raw_link,))
        row = await cursor.fetchone()
        if row and row[0]:
            parsed = json.loads(row[0])
        else:
            parsed = parse_share_link(raw_link)
            if not parsed:
                raise ValueError("Invalid or unknown node")

        # Get settings
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")

    manager = get_config_manager(core_type)

    # Ensure config file exists with proper structure
    try:
        config = manager.read_config()
    except FileNotFoundError:
        config = get_default_xray_config() if core_type == "xray" else get_default_singbox_config()

    # Always reset inbounds to the correct default structure
    # This ensures ports and listen addresses are always correct
    if core_type == "sing-box":
        default_config = get_default_singbox_config()
        config["inbounds"] = default_config["inbounds"]
        # Also set correct log level to suppress benign warnings
        config["log"] = default_config["log"]

        # Update proxy outbound with the new node
        proxy_outbound = parsed_to_singbox_outbound(parsed)
        outbounds = config.get("outbounds", [])
        proxy_index = next((i for i, ob in enumerate(outbounds) if ob.get("tag") == "proxy"), None)
        if proxy_index is not None:
            outbounds[proxy_index] = proxy_outbound
        else:
            outbounds.append(proxy_outbound)
        config["outbounds"] = outbounds

        # Update inbounds with proxy auth if credentials provided
        if proxy_username and proxy_password:
            for inbound in config.get("inbounds", []):
                if inbound.get("type") in ("http", "socks"):
                    inbound["users"] = [{
                        "username": proxy_username,
                        "password": proxy_password
                    }]
        else:
            # Remove users if no auth
            for inbound in config.get("inbounds", []):
                if "users" in inbound:
                    del inbound["users"]

        config_path = get_config_path()
    else:  # xray
        default_config = get_default_xray_config()
        config["inbounds"] = default_config["inbounds"]

        # Update proxy outbound with the new node
        proxy_outbound = parsed_to_xray_outbound(parsed)
        outbounds = config.get("outbounds", [])
        proxy_index = next((i for i, ob in enumerate(outbounds) if ob.get("tag") == "proxy"), None)
        if proxy_index is not None:
            outbounds[proxy_index] = proxy_outbound
        else:
            outbounds.append(proxy_outbound)
        config["outbounds"] = outbounds

        # Update inbounds with proxy auth if credentials provided
        if proxy_username and proxy_password:
            for inbound in config.get("inbounds", []):
                if inbound.get("protocol") in ("http", "socks"):
                    inbound.setdefault("settings", {}).setdefault("users", [])
                    inbound["settings"]["users"] = [{
                        "user": proxy_username,
                        "pass": proxy_password
                    }]
        else:
            # Remove users if no auth
            for inbound in config.get("inbounds", []):
                if "settings" in inbound and "users" in inbound.get("settings", {}):
                    del inbound["settings"]["users"]

        config_path = get_xray_config_path()

    # Write updated config
    manager.write_config(config)
    core_start(config_path, core_type)


async def _reapply_config_if_node_selected() -> None:
    """Restart core to apply config file changes. Config file is the source of truth."""
    settings_res = await get_settings("admin")  # Use admin user for internal calls
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()

    # Only restart if core is currently running
    if core_status().get("running"):
        core_restart(path, core_type)


@app.post("/api/nodes/latency-test")
async def node_latency_test(
    body: SelectNodeRequest,
    username: str = Depends(get_current_user),
):
    """Run real latency/speed test for a specific node using a separate temp core process. Does not change the current node."""
    raw_link = body.raw_link.strip()
    if not raw_link:
        raise HTTPException(status_code=400, detail="raw_link required")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.node_id is not None:
            await cursor.execute(
                "SELECT raw_link, parsed_json FROM nodes WHERE id = ? LIMIT 1",
                (body.node_id,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                raw_link = (row[0] or "").strip() or raw_link
                parsed = json.loads(row[1]) if row[1] else None
            else:
                parsed = None
        else:
            parsed = None
        if not parsed:
            parsed = parse_share_link(raw_link)
        test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip()
        core_type = await _get_setting(cursor, "core_type", "sing-box")
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid or unknown node")
    if not test_url:
        raise HTTPException(status_code=400, detail="Set a test URL in Core → Latency test and save.")
    try:
        if core_type == "xray":
            minimal_config = build_minimal_xray_config(parsed, LATENCY_TEST_HTTP_PORT)
        else:
            minimal_config = build_minimal_singbox_config(parsed, LATENCY_TEST_HTTP_PORT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    tmp_path = tmp.name
    try:
        json.dump(minimal_config, tmp, indent=2, ensure_ascii=False)
        tmp.close()
        proc = await asyncio.to_thread(start_temp_core, tmp_path, core_type)
        try:
            await asyncio.sleep(1.5)
            result = await asyncio.to_thread(
                run_latency_test, test_url, LATENCY_TEST_HTTP_PORT, "", ""
            )
        finally:
            await asyncio.to_thread(stop_temp_core, proc)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    real_ms = result.get("latency_ms") if result.get("success") else None
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.node_id is not None:
            await cursor.execute(
                "UPDATE nodes SET real_latency_ms = ? WHERE id = ?",
                (real_ms, body.node_id),
            )
        else:
            await cursor.execute(
                "UPDATE nodes SET real_latency_ms = ? WHERE raw_link = ?",
                (real_ms, raw_link),
            )
        await conn.commit()
    return result


# --- Proxy domains (config-based) ---
def _domain_to_routing_rule(domain_type: str, value: str, outbound: str, core_type: str) -> dict:
    """Convert a domain entry to a routing rule for config file."""
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


@app.get("/api/domains")
async def list_domains(username: str = Depends(get_current_user)):
    """List domains from config file route/routing section."""
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    try:
        config = manager.read_config()
        rules_key = "route" if core_type == "sing-box" else "routing"
        rules = config.get(rules_key, {}).get("rules", [])

        domains = []
        for i, rule in enumerate(rules):
            # Convert routing rules back to domain format
            if core_type == "sing-box":
                outbound = rule.get("outbound", "proxy")
                # Parse sing-box rule format
                if "domain" in rule:
                    for domain in rule.get("domain", []):
                        domains.append({"id": i, "type": "exact", "value": domain, "outbound": outbound})
                if "domain_suffix" in rule:
                    for suffix in rule.get("domain_suffix", []):
                        domains.append({"id": i, "type": "domain_suffix", "value": suffix.lstrip("."), "outbound": outbound})
                if "domain_keyword" in rule:
                    for keyword in rule.get("domain_keyword", []):
                        domains.append({"id": i, "type": "contains", "value": keyword, "outbound": outbound})
                if "domain_regex" in rule:
                    for regex in rule.get("domain_regex", []):
                        domains.append({"id": i, "type": "regex", "value": regex, "outbound": outbound})
            else:  # xray
                if rule.get("type") == "field":
                    domain_rule = rule.get("domain", [])
                    outbound = rule.get("outbound", "proxy")
                    for domain in domain_rule:
                        if ":" in domain:
                            rule_type, value = domain.split(":", 1)
                            type_map = {"full": "exact", "domain": "domain_suffix", "keyword": "contains", "regexp": "regex"}
                            domains.append({"id": i, "type": type_map.get(rule_type, "exact"), "value": value, "outbound": outbound})

        return {"domains": domains}
    except FileNotFoundError:
        # Config file doesn't exist yet, return empty list
        return {"domains": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/domains")
async def add_domain(
    body: DomainCreate,
    username: str = Depends(get_current_user),
):
    """Add domain to config file."""
    if body.type not in ("domain", "suffix", "keyword", "regex", "exact", "domain_suffix", "contains"):
        raise HTTPException(status_code=400, detail="Invalid type")
    if body.outbound not in ("proxy", "direct"):
        raise HTTPException(status_code=400, detail="outbound must be 'proxy' or 'direct'")
    value = (body.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Value is required")

    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    # Ensure config file exists
    try:
        config = manager.read_config()
    except FileNotFoundError:
        config = get_default_xray_config() if core_type == "xray" else get_default_singbox_config()

    rules_key = "route" if core_type == "sing-box" else "routing"

    # Convert domain to routing rule
    new_rule = _domain_to_routing_rule(body.type, value, body.outbound, core_type)

    if rules_key not in config:
        config[rules_key] = {"rules": [], "final": "direct"}
    if "rules" not in config[rules_key]:
        config[rules_key]["rules"] = []

    config[rules_key]["rules"].append(new_rule)
    manager.write_config(config)

    await _reapply_config_if_node_selected()

    # Return with id as the new index
    new_id = len(config[rules_key]["rules"]) - 1
    return {"id": new_id, "type": body.type, "value": value, "outbound": body.outbound}


@app.delete("/api/domains/{domain_id}")
async def delete_domain(
    domain_id: int,
    username: str = Depends(get_current_user),
):
    """Delete domain from config by index."""
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    try:
        config = manager.read_config()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    rules_key = "route" if core_type == "sing-box" else "routing"

    rules = config.get(rules_key, {}).get("rules", [])
    if 0 <= domain_id < len(rules):
        rules.pop(domain_id)
        manager.write_config(config)
        await _reapply_config_if_node_selected()
        return {"ok": True}
    else:
        raise HTTPException(status_code=404, detail="Domain not found")


def _parse_domain_line(line: str) -> tuple[str, str] | None:
    """Parse one line into (type, value) or None if empty/invalid."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    # *keyword* → contains
    if len(s) >= 2 and s.startswith("*") and s.endswith("*") and s.count("*") == 2:
        return ("contains", s[1:-1].strip())
    # *.domain.com → domain_suffix (value without leading *. for storage)
    if s.startswith("*."):
        return ("domain_suffix", s[2:].strip())
    # else exact domain/host
    return ("exact", s)


@app.post("/api/domains/bulk")
async def bulk_add_domains(
    body: DomainBulkRequest,
    username: str = Depends(get_current_user),
):
    """Import newline-separated list. Lines: exact domains, *.domain → domain_suffix, *word* → contains."""
    if body.outbound not in ("proxy", "direct"):
        raise HTTPException(status_code=400, detail="outbound must be 'proxy' or 'direct'")
    pairs = []
    for line in body.text.splitlines():
        parsed = _parse_domain_line(line)
        if parsed:
            type_, value = parsed
            if type_ not in ("domain", "suffix", "keyword", "regex", "exact", "domain_suffix", "contains"):
                continue
            if not value:
                continue
            pairs.append((type_, value))
    if not pairs:
        return {"added": 0, "message": "No valid lines to add"}

    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    # Ensure config file exists
    try:
        config = manager.read_config()
    except FileNotFoundError:
        config = get_default_xray_config() if core_type == "xray" else get_default_singbox_config()

    rules_key = "route" if core_type == "sing-box" else "routing"

    if rules_key not in config:
        config[rules_key] = {"rules": [], "final": "direct"}
    if "rules" not in config[rules_key]:
        config[rules_key]["rules"] = []

    # Add all domains as routing rules
    for type_, value in pairs:
        new_rule = _domain_to_routing_rule(type_, value, body.outbound, core_type)
        config[rules_key]["rules"].append(new_rule)

    manager.write_config(config)
    await _reapply_config_if_node_selected()

    return {"added": len(pairs), "message": f"Added {len(pairs)} domain rule(s)."}


# --- Manual config (share link) ---
@app.post("/api/manual/apply")
async def apply_manual_config(
    body: ManualConfigRequest,
    username: str = Depends(get_current_user),
):
    if body.share_link:
        parsed = parse_share_link(body.share_link.strip())
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid share link")
    elif body.raw_json:
        try:
            parsed = json.loads(body.raw_json.strip())
            # If user pasted a full sing-box config, take the first proxy outbound
            if isinstance(parsed.get("outbounds"), list):
                for ob in parsed["outbounds"]:
                    if isinstance(ob, dict) and ob.get("type") in ("vless", "vmess", "trojan", "shadowsocks"):
                        parsed = ob
                        break
            parsed["raw"] = body.raw_json[:200]
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")
    else:
        raise HTTPException(status_code=400, detail="Provide share_link or raw_json")
    raw_link = (parsed.get("raw") or "").strip()
    if not raw_link:
        raw_link = (body.share_link or "")[:200].strip() or ((body.raw_json or "")[:200].strip() if body.raw_json else "")
        parsed["raw"] = raw_link
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("DELETE FROM nodes WHERE source = 'manual'")
        await cursor.execute(
            "INSERT INTO nodes (source, raw_link, parsed_json, name, created_at) VALUES ('manual', ?, ?, ?, datetime('now'))",
            (raw_link, json.dumps(parsed, ensure_ascii=False), parsed.get("remark") or parsed.get("ps") or "manual"),
        )
        await cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
            (raw_link,),
        )
        await conn.commit()
    # Update the config file with the new manual node
    await _apply_node_config(raw_link)
    return {"ok": True}


def _usage_for_pid(pid: int | None) -> dict:
    """Return usage dict: connections (from process), upload_bytes/download_bytes (None unless Xray stats)."""
    out = {"connections": None, "upload_bytes": None, "download_bytes": None}
    if pid is None:
        return out
    try:
        import psutil
    except ImportError:
        return out
    try:
        p = psutil.Process(pid)
        out["connections"] = len(p.connections())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return out


XRAY_STATS_API_PORT = 10085


def _xray_traffic_bytes() -> tuple[int | None, int | None]:
    """Query Xray stats API; return (upload_bytes, download_bytes) for inbounds http-in + socks-in, or (None, None)."""
    try:
        r = subprocess.run(
            [XRAY_BIN, "api", "statsquery", "--server=127.0.0.1:%s" % XRAY_STATS_API_PORT],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if r.returncode != 0 or not r.stdout:
            return (None, None)
        data = json.loads(r.stdout)
        stat_list = data.get("stat") or []
        upload = 0
        download = 0
        for s in stat_list:
            name = (s.get("name") or "").strip()
            try:
                value = int(s.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if not name.endswith(">>>traffic>>>uplink") and not name.endswith(">>>traffic>>>downlink"):
                continue
            if "inbound>>>http-in>>>" in name or "inbound>>>socks-in>>>" in name:
                if name.endswith(">>>traffic>>>uplink"):
                    upload += value
                else:
                    download += value
        return (upload, download)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return (None, None)


def _singbox_traffic_bytes() -> tuple[int | None, int | None]:
    """Query sing-box experimental Clash API /traffic; return (upload_bytes, download_bytes) or (None, None)."""
    if os.environ.get(SINGBOX_CLASH_API_ENV, "").strip().lower() not in ("1", "true", "yes"):
        return (None, None)
    try:
        url = "http://127.0.0.1:%s/traffic" % SINGBOX_CLASH_API_PORT
        with urlopen(url, timeout=3) as r:
            # /traffic streams; read until we get a parseable line (SSE "data: {...}" or raw JSON)
            for _ in range(20):
                line = r.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                if raw.startswith("data:"):
                    raw = raw[5:].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # sing-box/Clash may use "Up"/"Down" (Go) or "up"/"down"
                up = data.get("up") if data.get("up") is not None else data.get("Up")
                down = data.get("down") if data.get("down") is not None else data.get("Down")
                if up is not None and down is not None:
                    return (int(up), int(down))
        return (None, None)
    except (URLError, json.JSONDecodeError, ValueError, OSError):
        return (None, None)


# --- Core status and control ---
def _get_ports_from_config(core_type: str) -> tuple[int, int]:
    """Get http and socks ports from config file. Returns (http_port, socks_port)."""
    try:
        manager = get_config_manager(core_type)
        config = manager.read_config()
        inbounds = config.get("inbounds", [])
        http_port = 8080
        socks_port = 1080

        for inbound in inbounds:
            if core_type == "sing-box":
                inbound_type = inbound.get("type", "")
                port = inbound.get("listen_port", 8080)
                if inbound_type == "http":
                    http_port = port
                elif inbound_type == "socks":
                    socks_port = port
                elif inbound_type == "mixed":
                    # Mixed type handles both HTTP and SOCKS on same port
                    http_port = port
                    socks_port = port
            else:  # xray
                protocol = inbound.get("protocol", "")
                port = inbound.get("port", 8080)
                if protocol == "http":
                    http_port = port
                elif protocol == "socks":
                    socks_port = port
        return (http_port, socks_port)
    except FileNotFoundError:
        # Config file doesn't exist, return defaults
        return (8080, 1080)


@app.get("/api/status")
async def status(username: str = Depends(get_current_user)):
    st = core_status()
    settings = await get_settings(username)
    selected_raw = settings.get("selected_node_raw") or ""
    selected_name = ""
    selected_latency_ms = None
    selected_real_latency_ms = None
    if selected_raw:
        async with db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT name, latency_ms, real_latency_ms FROM nodes WHERE raw_link = ? LIMIT 1",
                (selected_raw,),
            )
            row = await cursor.fetchone()
            if row:
                selected_name = row[0] or selected_raw[:50] + ("..." if len(selected_raw) > 50 else "")
                selected_latency_ms = row[1]
                selected_real_latency_ms = row[2]
            elif selected_raw:
                selected_name = selected_raw[:50] + ("..." if len(selected_raw) > 50 else "")
    # Usage: connection count from process; upload/download from Xray stats API or sing-box Clash API when enabled
    usage = _usage_for_pid(st.get("pid"))
    if st.get("running"):
        if settings.get("core_type") == "xray":
            up, down = _xray_traffic_bytes()
            if up is not None:
                usage["upload_bytes"] = up
            if down is not None:
                usage["download_bytes"] = down
        elif settings.get("core_type") == "sing-box":
            up, down = _singbox_traffic_bytes()
            if up is not None:
                usage["upload_bytes"] = up
            if down is not None:
                usage["download_bytes"] = down

    # Get ports from config file
    http_port, socks_port = _get_ports_from_config(settings.get("core_type", "sing-box"))

    return {
        "core": st,
        "core_type": settings.get("core_type", "sing-box"),
        "http_port": http_port,
        "socks_port": socks_port,
        "proxy_display_host": settings.get("proxy_display_host", "127.0.0.1"),
        "proxy_username": (settings.get("proxy_username") or "").strip() or "",
        "proxy_password": settings.get("proxy_password") or "",
        "latency_test_domain": (settings.get("latency_test_domain") or "https://example.com").strip() or "https://example.com",
        "last_refresh": settings.get("last_refresh", ""),
        "selected_node_raw": selected_raw[:80] + "..." if len(selected_raw) > 80 else selected_raw,
        "selected_node_name": selected_name,
        "selected_node_latency_ms": selected_latency_ms,
        "selected_node_real_latency_ms": selected_real_latency_ms,
        "usage": usage,
    }


@app.post("/api/core/start")
async def core_start_api(username: str = Depends(get_current_user)):
    """Start the core with the config file. If config file is missing, runs a refresh first."""
    from pathlib import Path
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()

    # If config file doesn't exist, try to refresh to create it
    if not Path(path).exists():
        await refresh_and_apply()
        return {"ok": True, "running": core_status()["running"]}
    ok = core_start(path, core_type)
    return {"ok": ok, "running": core_status()["running"]}


@app.post("/api/core/stop")
async def core_stop_api(username: str = Depends(get_current_user)):
    core_stop()
    return {"ok": True, "running": False}


@app.post("/api/core/restart")
async def core_restart_api(username: str = Depends(get_current_user)):
    """Restart the core with the current config file."""
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()
    core_restart(path, core_type)
    return {"ok": True, "running": core_status()["running"]}


@app.get("/api/core/logs")
async def core_logs(username: str = Depends(get_current_user), tail: int | None = None):
    """Return core logs. If tail is omitted, return full buffer (up to 2000 lines)."""
    if tail is None:
        lines = core_get_logs(tail=2000)
    else:
        lines = core_get_logs(tail=min(max(1, tail), 2000))
    return {"lines": lines}


@app.post("/api/core/latency-test")
async def core_latency_test(
    body: LatencyTestRequest | None = None,
    username: str = Depends(get_current_user),
):
    """Run a real latency/speed test via current proxy; save result to selected node for dashboard/node list."""
    settings_res = await get_settings(username)
    url = (body and body.url) or settings_res.get("latency_test_domain", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No test URL. Set a URL in Core → Latency test and save.")
    core_type = settings_res.get("core_type", "sing-box")
    http_port, _ = _get_ports_from_config(core_type)
    proxy_username = (settings_res.get("proxy_username") or "").strip()
    proxy_password = settings_res.get("proxy_password") or ""
    result = await asyncio.to_thread(run_latency_test, url, http_port, proxy_username, proxy_password)
    # Persist real latency for current node so dashboard shows it
    selected_raw = (settings_res.get("selected_node_raw") or "").strip()
    if selected_raw:
        real_ms = result.get("latency_ms") if result.get("success") else None
        async with db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "UPDATE nodes SET real_latency_ms = ? WHERE raw_link = ?",
                (real_ms, selected_raw),
            )
            await conn.commit()
    return result


@app.get("/api/config")
async def get_config(username: str = Depends(get_current_user)):
    """Return the current core config JSON from file (sing-box or Xray)."""
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    config_path = get_xray_config_path() if core_type == "xray" else get_config_path()

    try:
        manager = get_config_manager(core_type)
        config = manager.read_config()
        return {"config": config, "exists": True, "path": config_path, "is_custom": False}
    except FileNotFoundError:
        # Return default config if file doesn't exist
        default = get_default_config(core_type)
        return {"config": default, "exists": False, "path": config_path, "is_custom": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {str(e)}")


@app.get("/api/config/structure")
async def get_config_structure(username: str = Depends(get_current_user)):
    """Get available config sections based on core type."""
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")

    if core_type == "sing-box":
        sections = [
            {"name": "dns", "label": "DNS", "description": "DNS servers and rules"},
            {"name": "outbounds", "label": "Outbound", "description": "Proxy and direct outbounds"},
            {"name": "route", "label": "Rules", "description": "Routing rules"}
        ]
    else:  # xray
        sections = [
            {"name": "dns", "label": "DNS", "description": "DNS servers and rules"},
            {"name": "outbounds", "label": "Outbound", "description": "Proxy and direct outbounds"},
            {"name": "routing", "label": "Rules", "description": "Routing rules"}
        ]

    sections.append({"name": "all", "label": "All", "description": "Full configuration"})

    return {"sections": sections, "core_type": core_type}


@app.get("/api/config/section/{section_name}")
async def get_config_section(
    section_name: str,
    username: str = Depends(get_current_user)
):
    """Get a specific section of the config (log, dns, inbounds, outbounds, route, routing, all)."""
    # Validate section name
    valid_sections = ["log", "dns", "inbounds", "outbounds", "route", "routing", "all"]
    if section_name not in valid_sections:
        raise HTTPException(status_code=400, detail="Invalid section name")

    # Get config from file
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    try:
        config_json = manager.read_config()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")

    # Return specific section or full config
    if section_name == "all":
        return {"section": "all", "data": config_json, "core_type": core_type}

    # Map route→routing for Xray compatibility
    section_key = "routing" if section_name == "route" and core_type == "xray" else section_name

    if section_key not in config_json:
        raise HTTPException(status_code=404, detail=f"Section '{section_key}' not found in config")

    return {"section": section_name, "data": config_json[section_key], "core_type": core_type}


class ConfigSectionUpdate(BaseModel):
    data: Union[Dict[str, Any], List[Any]]


@app.put("/api/config/section/{section_name}")
async def update_config_section(
    section_name: str,
    body: ConfigSectionUpdate,
    username: str = Depends(get_current_user)
):
    """Update a specific section of the config file."""
    valid_sections = ["dns", "outbounds", "route", "routing", "inbounds", "log", "all"]
    if section_name not in valid_sections:
        raise HTTPException(status_code=400, detail="Invalid section name")

    # Get settings and config manager
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    manager = get_config_manager(core_type)

    try:
        # Validate section data
        section_data = body.data
        json.dumps(section_data)

        # When "all", write the entire config directly
        if section_name == "all":
            if not isinstance(section_data, dict):
                raise HTTPException(status_code=400, detail="Config data must be a dict when updating 'all'")
            manager.write_config(section_data)
            return {"ok": True, "message": "Full config updated successfully"}

        # Update section in config file
        manager.update_section(section_name, section_data)

        return {"ok": True, "message": f"Section '{section_name}' updated successfully"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


# --- API only; frontend is served separately ---
@app.get("/")
async def root():
    return {"api": "conduit", "docs": "/docs"}
