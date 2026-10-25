"""FastAPI app: auth, settings, nodes, domains, core status. The frontend is served by nginx."""
import asyncio
import json
import os
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import URLError
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Union
import aiosqlite
from fastapi import FastAPI, Depends, HTTPException, Header, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import hash_password, verify_password, create_access_token, decode_token
from database import init_db, db_connection
from share_links import parse_share_link
from latency import check_node_latency, check_nodes_latency
from config_generator import (
    build_minimal_singbox_config,
    build_minimal_xray_config,
    LATENCY_TEST_HTTP_PORT,
    NODE_TAG_PREFIX,
    MULTIPLEX_PROTOCOLS,
    PROTOCOLS,
    apply_node_outbounds,
    node_tag,
    singbox_outbound,
    to_model,
    xray_outbound,
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
from latency_test import run_latency_test
from url_utils import host_from_url
from config_file_manager import ConfigFileManager
from default_config import get_default_config, get_default_singbox_config, get_default_xray_config
from migration import migrate_db_to_config
from proxy_layout import (
    CLASH_API_PORT,
    FULL_HTTP_PORT,
    HYBRID_HTTP_PORT,
    PROXY_TAGS,
    XRAY_API_PORT,
    apply_proxy_layout,
    proxy_ports,
)


DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"


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
    node_mode: str | None = None  # "manual" (you pick the node) | "auto" (fastest node by real delay)
    verbose_logs: bool | None = None  # per-connection core logs; costs CPU under load
    tcp_fast_open: bool | None = None  # TCP Fast Open to nodes (needs kernel support on both ends)
    core_type: str | None = None  # "sing-box" | "xray"
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


class AddNodeRequest(BaseModel):
    share_link: str | None = None  # single vmess:// or vless:// etc
    raw_json: str | None = None    # or full sing-box outbound (we merge with inbounds)
    activate: bool = True          # also make it the active node


class SelectNodeRequest(BaseModel):
    raw_link: str
    node_id: int | None = None  # optional; preferred over raw_link to find the node


class UpdateNodeRequest(BaseModel):
    raw_link: str | None = None
    multiplex: str | None = None  # "off" | "h2mux" | "smux" | "yamux"


class LatencyTestRequest(BaseModel):
    url: str | None = None  # use settings latency_test_domain if omitted


# --- Lifespan: init DB, ensure admin, sync config ports ---
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
    await _import_config_only_proxy()
    # Bring the config in line with env ports and the node list, and start the core: nothing else starts it at boot
    try:
        await _rebuild_core_config(start="always")
    except ValueError:
        async with db_connection() as conn:
            core_type = await _get_setting(await conn.cursor(), "core_type", "sing-box")
        await _sync_config_layout(core_type)

    yield
    # shutdown: stop core?
    core_stop()


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
        "core_type": settings.get("core_type", "sing-box"),
        "selected_node_raw": settings.get("selected_node_raw", ""),
        "latency_test_domain": (settings.get("latency_test_domain") or "").strip() or DEFAULT_TEST_URL,
        "proxy_display_host": (settings.get("proxy_display_host") or "127.0.0.1").strip() or "127.0.0.1",
        "proxy_username": (settings.get("proxy_username") or "").strip() or "",
        "proxy_password": settings.get("proxy_password") or "",
        "node_mode": settings.get("node_mode", "manual"),
        "verbose_logs": settings.get("verbose_logs", "false") == "true",
        "tcp_fast_open": settings.get("tcp_fast_open", "false") == "true",
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
        old_core = await _get_setting(cursor, "core_type", "sing-box")
        if body.core_type is not None:
            if body.core_type not in ("sing-box", "xray"):
                raise HTTPException(status_code=400, detail="core_type must be 'sing-box' or 'xray'")
            if body.core_type != old_core:
                # Refuse before saving anything when the active node can't run on the new core
                selected_raw = (await _get_setting(cursor, "selected_node_raw", "")).strip()
                await cursor.execute("SELECT parsed_json FROM nodes WHERE raw_link = ?", (selected_raw,))
                row = await cursor.fetchone()
                if row and row[0]:
                    convert = xray_outbound if body.core_type == "xray" else singbox_outbound
                    try:
                        convert(json.loads(row[0]), "proxy")
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=f"The active node can't run on {body.core_type}: {e}")
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('core_type', ?)",
                (body.core_type,),
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
        if body.node_mode is not None:
            if body.node_mode not in ("manual", "auto"):
                raise HTTPException(status_code=400, detail="node_mode must be 'manual' or 'auto'")
            await cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('node_mode', ?)", (body.node_mode,))
        for key in ("verbose_logs", "tcp_fast_open"):
            value = getattr(body, key)
            if value is not None:
                await cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, "true" if value else "false")
                )
        await conn.commit()
    if body.core_type is not None and body.core_type != old_core:
        # Each core has its own config file: carry the Domains rules over, then run the new core
        try:
            source = get_config_manager(old_core).read_config()
            domains = _domains_from_config(source, old_core)
        except FileNotFoundError:
            domains = []
        target_manager = get_config_manager(body.core_type)
        try:
            target = target_manager.read_config()
        except FileNotFoundError:
            target = get_default_config(body.core_type)
        _replace_domain_rules(target, body.core_type, domains)
        target_manager.write_config(target)
        was_running = core_status().get("running")
        try:
            await _rebuild_core_config(start="always" if was_running else "never")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Switched to {body.core_type}, but the config can't be built: {e}")
    # Settings that end up in the core config: rebuild it and restart the core
    core_fields = ("proxy_username", "proxy_password", "node_mode", "verbose_logs", "tcp_fast_open")
    if any(getattr(body, f) is not None for f in core_fields):
        try:
            await _rebuild_core_config()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
    await _rebuild_core_config()
    return {"ok": True}


@app.put("/api/nodes/{node_id}")
async def update_node(
    node_id: int = Path(..., gt=0),
    body: UpdateNodeRequest = ...,
    username: str = Depends(get_current_user),
):
    """Update a node's share link and/or multiplex setting, then rebuild the config."""
    if body.multiplex is not None and body.multiplex not in ("off",) + MULTIPLEX_PROTOCOLS:
        raise HTTPException(status_code=400, detail="multiplex must be off, h2mux, smux or yamux")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT raw_link FROM nodes WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Node not found")
        old_raw = row[0]
        if body.raw_link is not None and body.raw_link.strip() != old_raw:
            raw_link = body.raw_link.strip()
            parsed = parse_share_link(raw_link)
            if not parsed:
                raise HTTPException(status_code=400, detail="Invalid share link")
            name = parsed.get("remark") or parsed.get("name") or parsed.get("ps") or raw_link[:50]
            await cursor.execute(
                "UPDATE nodes SET raw_link = ?, parsed_json = ?, name = ? WHERE id = ?",
                (raw_link, json.dumps(parsed, ensure_ascii=False), name, node_id),
            )
            if await _get_setting(cursor, "selected_node_raw", "") == old_raw:
                await cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)", (raw_link,)
                )
        if body.multiplex is not None:
            await cursor.execute("UPDATE nodes SET multiplex = ? WHERE id = ?", (body.multiplex, node_id))
        await conn.commit()
    try:
        await _rebuild_core_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.get("/api/nodes")
async def list_nodes(username: str = Depends(get_current_user)):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, source, raw_link, parsed_json, name, latency_ms, real_latency_ms, last_check, multiplex FROM nodes ORDER BY latency_ms ASC, id ASC"
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
            "multiplex": r[8] or "off",
        })
    return {"nodes": nodes}


@app.post("/api/nodes/select")
async def select_node(
    body: SelectNodeRequest,
    username: str = Depends(get_current_user),
):
    """Make a stored node the active one and regenerate config."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.node_id is not None:
            await cursor.execute("SELECT raw_link FROM nodes WHERE id = ?", (body.node_id,))
        else:
            await cursor.execute("SELECT raw_link FROM nodes WHERE raw_link = ?", (body.raw_link,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Node not found")
        raw_link = row[0]
        await cursor.execute("SELECT id FROM nodes WHERE raw_link = ?", (raw_link,))
        node_id = (await cursor.fetchone())[0]
        await cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
            (raw_link,),
        )
        await conn.commit()
    # sing-box manual mode: switch the selector live, so open connections and pools survive
    live = await asyncio.to_thread(_clash_select, node_tag(node_id))
    try:
        await _rebuild_core_config(start="never" if live else "always")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "live": live}


@app.post("/api/nodes/ping")
async def ping_nodes(username: str = Depends(get_current_user)):
    """TCP-connect latency from this server to every node, in parallel. Stores latency_ms."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, parsed_json FROM nodes")
        rows = await cursor.fetchall()
    nodes = []
    for node_id, parsed_json in rows:
        try:
            node = json.loads(parsed_json) if parsed_json else {}
        except json.JSONDecodeError:
            node = {}
        node["_id"] = node_id
        nodes.append(node)
    await check_nodes_latency(nodes)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        for node in nodes:
            await cursor.execute(
                "UPDATE nodes SET latency_ms = ?, last_check = ? WHERE id = ?",
                (node.get("latency_ms"), now, node["_id"]),
            )
        await conn.commit()
    return {"results": [{"id": n["_id"], "latency_ms": n.get("latency_ms")} for n in nodes]}


async def _get_setting(cursor, key: str, default: str) -> str:
    await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else default


async def _write_core_config(manager: ConfigFileManager, config: Dict[str, Any], core_type: str) -> None:
    """Write the core config with env ports, proxy auth and the full-tunnel rule enforced."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")
        verbose_logs = await _get_setting(cursor, "verbose_logs", "false") == "true"
    apply_proxy_layout(config, core_type, proxy_username, proxy_password, verbose_logs)
    manager.write_config(config)


async def _sync_config_layout(core_type: str) -> None:
    """Bring an existing config file in line with the env ports (e.g. after a port env var changed)."""
    manager = get_config_manager(core_type)
    try:
        config = manager.read_config()
    except FileNotFoundError:
        return
    await _write_core_config(manager, config, core_type)


def _clash(method: str, path: str, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Call sing-box's Clash API on loopback."""
    req = Request(
        f"http://127.0.0.1:{CLASH_API_PORT}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=2) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _clash_select(tag: str) -> bool:
    """Switch the "proxy" selector to tag without a restart. False when not possible (Xray, auto mode, core down)."""
    try:
        group = _clash("GET", "/proxies/proxy")
        if group.get("type", "").lower() != "selector" or tag not in group.get("all", []):
            return False
        _clash("PUT", "/proxies/proxy", {"name": tag})
        return True
    except (URLError, OSError, ValueError):
        return False


def _clash_current_node() -> str | None:
    """Tag of the node "proxy" currently uses (sing-box), or None."""
    try:
        return _clash("GET", "/proxies/proxy").get("now")
    except (URLError, OSError, ValueError):
        return None


async def _import_config_only_proxy() -> None:
    """Keep a working node that only exists in an old config file.

    Before the node list drove the config, "proxy" could be edited in the JSON editor without being in the
    list. Rebuilding from the list would drop it, so add it to the list (as pasted JSON) and make it active
    when the active selection doesn't point at a stored node.
    """
    async with db_connection() as conn:
        cursor = await conn.cursor()
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        selected_raw = (await _get_setting(cursor, "selected_node_raw", "")).strip()
        await cursor.execute("SELECT 1 FROM nodes WHERE raw_link = ?", (selected_raw,))
        if selected_raw and await cursor.fetchone():
            return
        try:
            config = get_config_manager(core_type).read_config()
        except (FileNotFoundError, ValueError):
            return
        proxy = next((o for o in config.get("outbounds", []) if isinstance(o, dict) and o.get("tag") == "proxy"), None)
        if not proxy or (proxy.get("type") or proxy.get("protocol")) not in PROTOCOLS:
            return  # absent, or already a selector/urltest group built from the list
        node = {k: v for k, v in proxy.items() if k != "tag"}
        try:
            to_model(node)
        except ValueError:
            return
        raw = json.dumps(node, ensure_ascii=False)[:200]
        node["raw"] = raw
        await cursor.execute(
            """INSERT INTO nodes (source, raw_link, parsed_json, name, created_at) VALUES ('manual', ?, ?, ?, datetime('now'))
               ON CONFLICT(raw_link) DO NOTHING""",
            (raw, json.dumps(node, ensure_ascii=False), "Imported from previous config"),
        )
        await cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)", (raw,))
        await conn.commit()


async def _rebuild_core_config(start: str = "if_running") -> None:
    """Rebuild node outbounds from the node list and settings, write the config, and (re)start the core.

    Every config change goes through here: adding/editing/deleting nodes, switching, mode and auth settings.
    start: "always" (re)starts the core when there are nodes (boot, "Use", "Add & use"); "if_running" only
    restarts a running core, so a core you stopped stays stopped; "never" only writes the file.
    """
    async with db_connection() as conn:
        cursor = await conn.cursor()
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        selected_raw = (await _get_setting(cursor, "selected_node_raw", "")).strip()
        mode = await _get_setting(cursor, "node_mode", "manual")
        test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip() or DEFAULT_TEST_URL
        tcp_fast_open = await _get_setting(cursor, "tcp_fast_open", "false") == "true"
        await cursor.execute("SELECT id, raw_link, parsed_json, multiplex FROM nodes ORDER BY id")
        rows = await cursor.fetchall()
    nodes, active_id = [], None
    for node_id, raw_link, parsed_json, multiplex in rows:
        parsed = json.loads(parsed_json) if parsed_json else parse_share_link(raw_link)
        if not parsed:
            continue
        nodes.append({"id": node_id, "parsed": parsed, "multiplex": multiplex or "off"})
        if raw_link == selected_raw:
            active_id = node_id

    manager = get_config_manager(core_type)
    try:
        config = manager.read_config()
    except FileNotFoundError:
        config = get_default_config(core_type)
    apply_node_outbounds(config, core_type, nodes, mode, active_id, test_url, tcp_fast_open)
    await _write_core_config(manager, config, core_type)
    running = core_status().get("running")
    if (start == "always" and nodes) or (start != "never" and running):
        core_start(get_xray_config_path() if core_type == "xray" else get_config_path(), core_type)


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
        # Same default the UI shows; databases from older versions never stored one
        test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip() or DEFAULT_TEST_URL
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
                "domain_suffix": [clean_value]
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
                    "domain_suffix": [clean_value]
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
                "outboundTag": outbound
            }
        elif domain_type == "domain_suffix":
            clean_value = value.lstrip(".")
            return {
                "type": "field",
                "domain": [f"domain:{clean_value}"],
                "outboundTag": outbound
            }
        elif domain_type == "contains":
            return {
                "type": "field",
                "domain": [f"keyword:{value}"],
                "outboundTag": outbound
            }
        elif domain_type == "regex":
            return {
                "type": "field",
                "domain": [f"regexp:{value}"],
                "outboundTag": outbound
            }
        else:
            # Legacy types
            if domain_type == "domain":
                return {
                    "type": "field",
                    "domain": [f"full:{value}"],
                    "outboundTag": outbound
                }
            elif domain_type == "suffix":
                clean_value = value.lstrip(".")
                return {
                    "type": "field",
                    "domain": [f"domain:{clean_value}"],
                    "outboundTag": outbound
                }
            elif domain_type == "keyword":
                return {
                    "type": "field",
                    "domain": [f"keyword:{value}"],
                    "outboundTag": outbound
                }
            # Default to exact
            return {
                "type": "field",
                "domain": [f"full:{value}"],
                "outboundTag": outbound
            }


XRAY_DOMAIN_TYPES = {"full": "exact", "domain": "domain_suffix", "keyword": "contains", "regexp": "regex"}


def _domains_from_config(config: Dict[str, Any], core_type: str) -> List[Dict[str, Any]]:
    """Domain entries ({id, type, value, outbound}) from a core config's routing rules; id is the rule index."""
    rules = config.get("route" if core_type == "sing-box" else "routing", {}).get("rules", [])
    domains = []
    for i, rule in enumerate(rules):
        if core_type == "sing-box":
            outbound = rule.get("outbound", "proxy")
            for key, kind in (("domain", "exact"), ("domain_suffix", "domain_suffix"),
                              ("domain_keyword", "contains"), ("domain_regex", "regex")):
                for value in rule.get(key, []):
                    domains.append({"id": i, "type": kind, "value": value.lstrip(".") if kind == "domain_suffix" else value, "outbound": outbound})
        else:
            # balancerTag "proxy" is the auto-mode form of outboundTag "proxy"; "outbound" is what old versions wrote
            outbound = rule.get("outboundTag") or rule.get("balancerTag") or rule.get("outbound") or "proxy"
            for domain in rule.get("domain", []):
                prefix, sep, value = domain.partition(":")
                if not sep:  # a plain Xray string is a substring match
                    domains.append({"id": i, "type": "contains", "value": domain, "outbound": outbound})
                elif prefix in XRAY_DOMAIN_TYPES:
                    domains.append({"id": i, "type": XRAY_DOMAIN_TYPES[prefix], "value": value, "outbound": outbound})
    return domains


def _replace_domain_rules(config: Dict[str, Any], core_type: str, domains: List[Dict[str, Any]]) -> None:
    """Drop the config's domain rules and add the given entries (other rules, e.g. Xray's api rule, stay)."""
    key = "route" if core_type == "sing-box" else "routing"
    section = config.setdefault(key, {})
    domain_keys = ("domain", "domain_suffix", "domain_keyword", "domain_regex")
    kept = [r for r in section.get("rules", []) if not any(k in r for k in domain_keys)]
    section["rules"] = kept + [_domain_to_routing_rule(d["type"], d["value"], d["outbound"], core_type) for d in domains]


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

        domains = _domains_from_config(config, core_type)
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
    await _write_core_config(manager, config, core_type)

    await _rebuild_core_config()

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
        await _write_core_config(manager, config, core_type)
        await _rebuild_core_config()
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

    await _write_core_config(manager, config, core_type)
    await _rebuild_core_config()

    return {"added": len(pairs), "message": f"Added {len(pairs)} domain rule(s)."}


# --- Add node (share link or raw outbound JSON) ---
@app.post("/api/nodes")
async def add_node(
    body: AddNodeRequest,
    username: str = Depends(get_current_user),
):
    """Add a node to the list (adding the same link again updates it). With activate=true it also becomes active."""
    if body.share_link:
        parsed = parse_share_link(body.share_link.strip())
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid share link")
    elif body.raw_json:
        try:
            parsed = json.loads(body.raw_json.strip())
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="Paste one outbound object or a full sing-box/Xray config")
        # A full sing-box or Xray config: take its first proxy outbound
        if isinstance(parsed.get("outbounds"), list):
            parsed = next(
                (ob for ob in parsed["outbounds"]
                 if isinstance(ob, dict) and (ob.get("type") or ob.get("protocol")) in PROTOCOLS),
                None,
            )
            if parsed is None:
                raise HTTPException(status_code=400, detail="No vless/vmess/trojan/shadowsocks outbound in that config")
        parsed["raw"] = body.raw_json[:200]
    else:
        raise HTTPException(status_code=400, detail="Provide share_link or raw_json")
    try:
        to_model(parsed)  # rejects incomplete or unsupported nodes before they are stored
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    raw_link = (parsed.get("raw") or "").strip()
    if not raw_link:
        raw_link = (body.share_link or "")[:200].strip() or ((body.raw_json or "")[:200].strip() if body.raw_json else "")
        parsed["raw"] = raw_link
    name = parsed.get("remark") or parsed.get("ps") or parsed.get("name") or parsed.get("tag") or raw_link[:50]
    latency_ms = await check_node_latency(parsed)
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            """INSERT INTO nodes (source, raw_link, parsed_json, name, latency_ms, last_check, created_at)
               VALUES ('manual', ?, ?, ?, ?, datetime('now'), datetime('now'))
               ON CONFLICT(raw_link) DO UPDATE SET
                 parsed_json = excluded.parsed_json, name = excluded.name,
                 latency_ms = excluded.latency_ms, last_check = excluded.last_check""",
            (raw_link, json.dumps(parsed, ensure_ascii=False), name, latency_ms),
        )
        await cursor.execute("SELECT id FROM nodes WHERE raw_link = ?", (raw_link,))
        node_id = (await cursor.fetchone())[0]
        if body.activate:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
                (raw_link,),
            )
        await conn.commit()
    # The node list changed, so the outbounds change: rebuild (and restart) even when not activating
    try:
        await _rebuild_core_config(start="always" if body.activate else "if_running")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": node_id, "latency_ms": latency_ms}


def _usage_for_pid(pid: int | None) -> dict:
    """Return usage dict: connections (open sockets of the core), upload_bytes/download_bytes (filled in by the caller).

    Uses the core's open file descriptor count: a directory listing of /proc/<pid>/fd. The previous
    psutil connections() parsed the whole kernel TCP table on every poll, which got slower as load grew.
    """
    out = {"connections": None, "upload_bytes": None, "download_bytes": None}
    if pid is None:
        return out
    try:
        import psutil
    except ImportError:
        return out
    try:
        p = psutil.Process(pid)
        out["connections"] = p.num_fds()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return out


def _xray_traffic_bytes() -> tuple[int | None, int | None]:
    """Query Xray stats API; return (upload_bytes, download_bytes) for the proxy inbounds, or (None, None)."""
    try:
        r = subprocess.run(
            [XRAY_BIN, "api", "statsquery", "--server=127.0.0.1:%s" % XRAY_API_PORT],
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
            if any(f"inbound>>>{tag}>>>" in name for tag in PROXY_TAGS):
                if name.endswith(">>>traffic>>>uplink"):
                    upload += value
                else:
                    download += value
        return (upload, download)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return (None, None)


def _singbox_traffic_bytes() -> tuple[int | None, int | None]:
    """Query sing-box Clash API /traffic; return (upload_bytes, download_bytes) or (None, None)."""
    try:
        url = "http://127.0.0.1:%s/traffic" % CLASH_API_PORT
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
@app.get("/api/status")
async def status(username: str = Depends(get_current_user)):
    st = core_status()
    settings = await get_settings(username)
    selected_raw = settings.get("selected_node_raw") or ""
    selected_name = ""
    selected_latency_ms = None
    selected_real_latency_ms = None
    node_mode = settings.get("node_mode", "manual")
    active_node_id = None
    if node_mode == "auto" and st.get("running") and settings.get("core_type") != "xray":
        # Auto mode: the node in use is whatever the urltest group picked, not the stored selection
        tag = await asyncio.to_thread(_clash_current_node) or ""
        if tag.startswith(NODE_TAG_PREFIX) and tag[len(NODE_TAG_PREFIX):].isdigit():
            active_node_id = int(tag[len(NODE_TAG_PREFIX):])
    if selected_raw or active_node_id:
        async with db_connection() as conn:
            cursor = await conn.cursor()
            if active_node_id:
                await cursor.execute(
                    "SELECT name, latency_ms, real_latency_ms, raw_link, id FROM nodes WHERE id = ?", (active_node_id,)
                )
            else:
                await cursor.execute(
                    "SELECT name, latency_ms, real_latency_ms, raw_link, id FROM nodes WHERE raw_link = ? LIMIT 1",
                    (selected_raw,),
                )
            row = await cursor.fetchone()
            if row:
                selected_raw, active_node_id = row[3], row[4]
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

    return {
        "core": st,
        "core_type": settings.get("core_type", "sing-box"),
        **proxy_ports(),
        "proxy_display_host": settings.get("proxy_display_host", "127.0.0.1"),
        "proxy_username": (settings.get("proxy_username") or "").strip() or "",
        "proxy_password": settings.get("proxy_password") or "",
        "latency_test_domain": (settings.get("latency_test_domain") or "https://example.com").strip() or "https://example.com",
        "selected_node_raw": selected_raw[:80] + "..." if len(selected_raw) > 80 else selected_raw,
        "selected_node_name": selected_name,
        "node_mode": node_mode,
        "active_node_id": active_node_id,
        "selected_node_latency_ms": selected_latency_ms,
        "selected_node_real_latency_ms": selected_real_latency_ms,
        "usage": usage,
    }


@app.post("/api/core/start")
async def core_start_api(username: str = Depends(get_current_user)):
    """Start the core with the config file. If the file is missing, it is built from the active node."""
    from pathlib import Path
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()

    if not Path(path).exists():
        selected_raw = (settings_res.get("selected_node_raw") or "").strip()
        if not selected_raw:
            raise HTTPException(status_code=400, detail="No active node. Add a node on the Proxy page and use it.")
        try:
            await _rebuild_core_config(start="always")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True, "running": core_status()["running"]}
    await _sync_config_layout(core_type)
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
    await _sync_config_layout(core_type)
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
    # Prefer the full-tunnel port so the test always measures the node, whatever the Domains rules say
    http_port = FULL_HTTP_PORT or HYBRID_HTTP_PORT
    if http_port is None:
        raise HTTPException(status_code=400, detail="No HTTP proxy port is enabled")
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
            await _write_core_config(manager, section_data, core_type)
            return {"ok": True, "message": "Full config updated successfully"}

        # Update section in config file (inbounds always follow the env ports)
        config = manager.read_config()
        config[section_name] = section_data
        await _write_core_config(manager, config, core_type)

        return {"ok": True, "message": f"Section '{section_name}' updated successfully"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


# --- API only; frontend is served separately ---
@app.get("/")
async def root():
    return {"api": "conduit", "docs": "/docs"}
