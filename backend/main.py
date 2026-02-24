"""FastAPI app: auth, settings, subscription, nodes, domains, core status. Serves frontend static."""
import json
import os
import subprocess
from urllib.request import urlopen
from urllib.error import URLError
from contextlib import asynccontextmanager
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
    write_config,
    parsed_to_singbox_outbound,
    SINGBOX_CLASH_API_PORT,
    SINGBOX_CLASH_API_ENV,
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
)
from scheduler import refresh_and_apply, start_scheduler, run_refresh_once
from latency_test import run_latency_test
from url_utils import host_from_url


# --- Auth dependency ---
async def get_current_user(authorization: str | None = Header(None)) -> str:
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    username = decode_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


# --- Pydantic models ---
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SettingUpdate(BaseModel):
    subscription_url: str | None = None
    http_port: int | None = None
    socks_port: int | None = None
    core_type: str | None = None  # "sing-box" | "xray"
    refresh_interval_minutes: int | None = None  # 1–1440
    auto_switch_best: bool | None = None
    latency_test_domain: str | None = None  # e.g. "https://example.com" or "http://example.com/file.txt"
    proxy_display_host: str | None = None  # host/IP shown in Dashboard "How to use the proxy" (display only)
    proxy_username: str | None = None  # optional auth for HTTP/SOCKS proxy (empty = no auth)
    proxy_password: str | None = None  # optional auth for HTTP/SOCKS proxy


class DomainCreate(BaseModel):
    type: str  # domain, suffix, keyword, regex
    value: str


class DomainBulkRequest(BaseModel):
    text: str  # newline-separated list: exact domains, *.domain.com → domain_suffix, *keyword* → contains


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


import asyncio

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
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
    settings = {r[0]: r[1] for r in rows}
    return {
        "subscription_url": settings.get("subscription_url", ""),
        "http_port": int(settings.get("http_port", "8080")),
        "socks_port": int(settings.get("socks_port", "1080")),
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
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.subscription_url is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('subscription_url', ?)",
                (body.subscription_url,),
            )
        if body.http_port is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('http_port', ?)",
                (str(body.http_port),),
            )
        if body.socks_port is not None:
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('socks_port', ?)",
                (str(body.socks_port),),
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
            # Automatically add latency test host to domain list so it appears in Domains and routes through proxy
            host = host_from_url(val)
            if host:
                await cursor.execute("SELECT 1 FROM proxy_domains WHERE type = 'domain' AND value = ?", (host,))
                if await cursor.fetchone() is None:
                    await cursor.execute("INSERT INTO proxy_domains (type, value) VALUES ('domain', ?)", (host,))
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
        async with db_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT type, value FROM proxy_domains ORDER BY id")
            domains = [{"type": r[0], "value": r[1]} for r in await cursor.fetchall()]
            domains = await _domains_with_latency_test(cursor, domains)
            http_port = int(await _get_setting(cursor, "http_port", "8080"))
            socks_port = int(await _get_setting(cursor, "socks_port", "1080"))
            core_type = await _get_setting(cursor, "core_type", "sing-box")
            proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
            proxy_password = await _get_setting(cursor, "proxy_password", "")
        if core_type == "xray":
            config = build_xray_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
            config_path = get_xray_config_path()
        else:
            config = build_singbox_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
            config_path = get_config_path()
        write_config(config, config_path)
        core_start(config_path, core_type)
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
        await cursor.execute("SELECT type, value FROM proxy_domains ORDER BY id")
        domains = [{"type": r[0], "value": r[1]} for r in await cursor.fetchall()]
        domains = await _domains_with_latency_test(cursor, domains)
        http_port = await _get_setting(cursor, "http_port", "8080")
        socks_port = await _get_setting(cursor, "socks_port", "1080")
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")
        await conn.commit()
    http_port = int(http_port)
    socks_port = int(socks_port)
    if core_type == "xray":
        config = build_xray_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
        config_path = get_xray_config_path()
    else:
        config = build_singbox_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
        config_path = get_config_path()
    write_config(config, config_path)
    core_start(config_path, core_type)
    return {"ok": True}


async def _get_setting(cursor, key: str, default: str) -> str:
    await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else default


async def _domains_with_latency_test(cursor, domains: list) -> list:
    """Merge latency_test_domain host into the domain list if not already present (so latency test goes through proxy)."""
    test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip()
    host = host_from_url(test_url) if test_url else None
    if not host:
        return domains
    if any((d.get("value") or "").strip() == host for d in domains):
        return domains
    return domains + [{"type": "domain", "value": host}]


async def _apply_node_config(raw_link: str) -> None:
    """Build config for the given node (by raw_link), write and start core. Does not update settings."""
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
        await cursor.execute("SELECT type, value FROM proxy_domains ORDER BY id")
        domains = [{"type": r[0], "value": r[1]} for r in await cursor.fetchall()]
        domains = await _domains_with_latency_test(cursor, domains)
        http_port = int(await _get_setting(cursor, "http_port", "8080"))
        socks_port = int(await _get_setting(cursor, "socks_port", "1080"))
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")
    if core_type == "xray":
        config = build_xray_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
        config_path = get_xray_config_path()
    else:
        config = build_singbox_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
        config_path = get_config_path()
    write_config(config, config_path)
    core_start(config_path, core_type)


async def _reapply_config_if_node_selected() -> None:
    """If a node is selected, rebuild config (with current domains) and restart core. Used after domain add/delete."""
    async with db_connection() as conn:
        cursor = await conn.cursor()
        selected_raw = (await _get_setting(cursor, "selected_node_raw", "") or "").strip()
    if selected_raw:
        try:
            await _apply_node_config(selected_raw)
        except ValueError:
            pass


@app.post("/api/nodes/latency-test")
async def node_latency_test(
    body: SelectNodeRequest,
    username: str = Depends(get_current_user),
):
    """Run real latency/speed test for a specific node. Temporarily switches to that node, runs test, restores."""
    raw_link = body.raw_link.strip()
    if not raw_link:
        raise HTTPException(status_code=400, detail="raw_link required")
    # When node_id is provided (e.g. subscription nodes), load canonical raw_link from DB so apply/update match
    link_to_apply = raw_link
    async with db_connection() as conn:
        cursor = await conn.cursor()
        if body.node_id is not None:
            await cursor.execute(
                "SELECT raw_link, parsed_json FROM nodes WHERE id = ? LIMIT 1",
                (body.node_id,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                link_to_apply = (row[0] or "").strip() or raw_link
        selected = await _get_setting(cursor, "selected_node_raw", "")
        test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip()
        http_port = int(await _get_setting(cursor, "http_port", "8080"))
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")
    if not test_url:
        raise HTTPException(status_code=400, detail="Set a test URL in Core → Latency test and save.")
    if link_to_apply != selected:
        try:
            await _apply_node_config(link_to_apply)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await asyncio.to_thread(
            run_latency_test, test_url, http_port, proxy_username, proxy_password
        )
        # Persist real latency for this node (by id when provided, else by raw_link so subscription nodes are updated reliably)
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
    finally:
        if link_to_apply != selected and selected:
            await _apply_node_config(selected)
    return result


# --- Proxy domains ---
@app.get("/api/domains")
async def list_domains(username: str = Depends(get_current_user)):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, type, value FROM proxy_domains ORDER BY id")
        rows = await cursor.fetchall()
    return {"domains": [{"id": r[0], "type": r[1], "value": r[2]} for r in rows]}


@app.post("/api/domains")
async def add_domain(
    body: DomainCreate,
    username: str = Depends(get_current_user),
):
    if body.type not in ("domain", "suffix", "keyword", "regex", "exact", "domain_suffix", "contains"):
        raise HTTPException(status_code=400, detail="Invalid type")
    value = (body.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Value is required")
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "INSERT INTO proxy_domains (type, value) VALUES (?, ?)",
            (body.type, value),
        )
        await cursor.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        rid = int(row[0]) if row else 0
        await conn.commit()
    await _reapply_config_if_node_selected()
    return {"id": rid, "type": body.type, "value": value}


@app.delete("/api/domains/{domain_id}")
async def delete_domain(
    domain_id: int,
    username: str = Depends(get_current_user),
):
    async with db_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute("DELETE FROM proxy_domains WHERE id = ?", (domain_id,))
        await conn.commit()
    await _reapply_config_if_node_selected()
    return {"ok": True}


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
    async with db_connection() as conn:
        cursor = await conn.cursor()
        for type_, value in pairs:
            await cursor.execute(
                "INSERT INTO proxy_domains (type, value) VALUES (?, ?)",
                (type_, value),
            )
        await conn.commit()
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
        await cursor.execute("SELECT type, value FROM proxy_domains ORDER BY id")
        domains = [{"type": r[0], "value": r[1]} for r in await cursor.fetchall()]
        domains = await _domains_with_latency_test(cursor, domains)
        http_port = await _get_setting(cursor, "http_port", "8080")
        socks_port = await _get_setting(cursor, "socks_port", "1080")
        core_type = await _get_setting(cursor, "core_type", "sing-box")
        proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
        proxy_password = await _get_setting(cursor, "proxy_password", "")
        await conn.commit()
    http_port = int(http_port)
    socks_port = int(socks_port)
    try:
        if core_type == "xray":
            config = build_xray_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
            config_path = get_xray_config_path()
        else:
            config = build_singbox_config(parsed, domains, http_port, socks_port, proxy_username, proxy_password)
            config_path = get_config_path()
        write_config(config, config_path)
        core_start(config_path, core_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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

    return {
        "core": st,
        "core_type": settings.get("core_type", "sing-box"),
        "http_port": int(settings["http_port"]),
        "socks_port": int(settings["socks_port"]),
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
    """Start the core. If config is missing, runs a refresh first (which also starts the core)."""
    from pathlib import Path
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()
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
    """Restart the core. Refreshes config from DB then stop+start."""
    await refresh_and_apply()
    settings_res = await get_settings(username)
    core_type = settings_res.get("core_type", "sing-box")
    path = get_xray_config_path() if core_type == "xray" else get_config_path()
    ok = core_restart(path, core_type)
    return {"ok": ok, "running": core_status()["running"]}


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
    http_port = int(settings_res.get("http_port", "8080"))
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


# --- API only; frontend is served separately ---
@app.get("/")
async def root():
    return {"api": "conduit", "docs": "/docs"}
