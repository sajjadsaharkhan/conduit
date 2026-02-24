"""Scheduler: configurable interval refresh, latency check, optionally auto-switch to best node."""
import asyncio
import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import db_connection
from subscription import fetch_subscription
from latency import check_nodes_latency, select_best_node
from config_generator import build_singbox_config, build_xray_config, write_config
from core_manager import start as core_start, get_config_path, get_xray_config_path
from url_utils import host_from_url

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _get_setting(cursor, key: str, default: str = "") -> str:
    await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else default


async def _get_proxy_domains(cursor) -> list:
    await cursor.execute("SELECT type, value FROM proxy_domains ORDER BY id")
    rows = await cursor.fetchall()
    domains = [{"type": r[0], "value": r[1]} for r in rows]
    # Include latency test domain so latency test goes through proxy
    test_url = (await _get_setting(cursor, "latency_test_domain", "")).strip()
    host = host_from_url(test_url) if test_url else None
    if host and not any((d.get("value") or "").strip() == host for d in domains):
        domains = domains + [{"type": "domain", "value": host}]
    return domains


async def _get_http_socks_ports(cursor) -> tuple:
    http_port = await _get_setting(cursor, "http_port", "8080")
    socks_port = await _get_setting(cursor, "socks_port", "1080")
    return int(http_port), int(socks_port)


async def refresh_and_apply() -> None:
    """Fetch subscription, parse nodes, latency check; if auto_switch_best, pick best and apply config."""
    try:
        async with db_connection() as conn:
            cursor = await conn.cursor()
            sub_url = await _get_setting(cursor, "subscription_url")
            if not sub_url:
                logger.info("No subscription_url set, skip refresh")
                return
            refresh_min = int(await _get_setting(cursor, "refresh_interval_minutes", "1"))
            refresh_min = max(1, min(1440, refresh_min))
            last_refresh = await _get_setting(cursor, "last_refresh", "")
            if last_refresh:
                try:
                    last_dt = datetime.fromisoformat(last_refresh.replace("Z", "+00:00"))
                    if datetime.utcnow() - last_dt.replace(tzinfo=None) < timedelta(minutes=refresh_min):
                        logger.debug("Skip refresh: interval not reached")
                        return
                except Exception:
                    pass
            try:
                parsed_list = await fetch_subscription(sub_url)
            except Exception as e:
                logger.warning("Fetch subscription failed: %s", e)
                await cursor.execute("SELECT parsed_json FROM nodes WHERE source = 'subscription'")
                rows = await cursor.fetchall()
                parsed_list = []
                for (raw_json,) in rows:
                    if raw_json:
                        try:
                            parsed_list.append(json.loads(raw_json))
                        except Exception:
                            pass
                if not parsed_list:
                    return

            if not parsed_list:
                logger.info("No nodes from subscription")
                return

            for n in parsed_list:
                if "remark" not in n and "ps" in n:
                    n["remark"] = n["ps"]
                if "name" not in n:
                    n["name"] = n.get("remark") or n.get("ps") or ""

            await check_nodes_latency(parsed_list)
            auto_switch = (await _get_setting(cursor, "auto_switch_best", "true")).lower() in ("true", "1", "yes")
            best = select_best_node(parsed_list) if auto_switch else None
            selected_raw = await _get_setting(cursor, "selected_node_raw", "")
            if auto_switch and best:
                selected_raw = best.get("raw", "")

            now = datetime.utcnow().isoformat()
            await cursor.execute("DELETE FROM nodes WHERE source = 'subscription'")
            for n in parsed_list:
                await cursor.execute(
                    """INSERT INTO nodes (source, raw_link, parsed_json, name, latency_ms, last_check, created_at)
                       VALUES ('subscription', ?, ?, ?, ?, ?, ?)""",
                    (
                        n.get("raw", ""),
                        json.dumps(n, ensure_ascii=False),
                        n.get("name") or n.get("remark") or "",
                        n.get("latency_ms"),
                        now,
                        now,
                    ),
                )
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('selected_node_raw', ?)",
                (selected_raw,),
            )
            await cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('last_refresh', ?)",
                (now,),
            )
            await conn.commit()

            if not selected_raw:
                logger.info("Refresh done, no node selected")
                return
            # Resolve current selected node from list for config
            current = next((n for n in parsed_list if n.get("raw") == selected_raw), None)
            if not current:
                await cursor.execute("SELECT parsed_json FROM nodes WHERE raw_link = ? LIMIT 1", (selected_raw,))
                row = await cursor.fetchone()
                if row and row[0]:
                    try:
                        current = json.loads(row[0])
                        current["raw"] = selected_raw
                    except Exception:
                        pass
            if not current:
                logger.info("Selected node not in list and not in DB, skip apply")
                return
            domains = await _get_proxy_domains(cursor)
            http_port, socks_port = await _get_http_socks_ports(cursor)
            core_type = await _get_setting(cursor, "core_type", "sing-box")
            proxy_username = (await _get_setting(cursor, "proxy_username", "")).strip()
            proxy_password = await _get_setting(cursor, "proxy_password", "")
            if core_type == "xray":
                config = build_xray_config(current, domains, http_port, socks_port, proxy_username, proxy_password)
                config_path = get_xray_config_path()
            else:
                config = build_singbox_config(current, domains, http_port=http_port, socks_port=socks_port, proxy_username=proxy_username, proxy_password=proxy_password)
                config_path = get_config_path()
            write_config(config, config_path)
            core_start(config_path, core_type)
            logger.info("Refresh done, node applied")
    except Exception as e:
        logger.exception("Refresh failed: %s", e)


def start_scheduler() -> None:
    """Run refresh every 1 minute."""
    scheduler.add_job(
        refresh_and_apply,
        trigger=IntervalTrigger(minutes=1),
        id="refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


async def run_refresh_once() -> None:
    """Run one refresh (call from app startup)."""
    await refresh_and_apply()
