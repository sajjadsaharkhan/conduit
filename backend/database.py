"""SQLite database and schema for Conduit."""
import aiosqlite
import os
from contextlib import asynccontextmanager
from pathlib import Path

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/conduit.db")
# Wait up to 30s for lock (avoids "database is locked" under concurrent use)
DB_TIMEOUT = 30


async def get_db_path() -> str:
    """Ensure data dir exists and return DB path."""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def init_db() -> None:
    """Create tables if they don't exist."""
    db_path = await get_db_path()
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proxy_domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('domain', 'suffix', 'keyword', 'regex', 'exact', 'domain_suffix', 'contains')),
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL CHECK(source IN ('subscription', 'manual')),
                raw_link TEXT NOT NULL,
                parsed_json TEXT,
                name TEXT,
                latency_ms INTEGER,
                last_check TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(raw_link)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source);
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
        """)
        await db.commit()
        # Migrate proxy_domains if it has the old CHECK (missing exact, domain_suffix, contains)
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='proxy_domains'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row and row[0] and "'exact'" not in row[0]:
            await db.execute("""
                CREATE TABLE proxy_domains_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL CHECK(type IN ('domain', 'suffix', 'keyword', 'regex', 'exact', 'domain_suffix', 'contains')),
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute(
                "INSERT INTO proxy_domains_new (id, type, value, created_at) SELECT id, type, value, created_at FROM proxy_domains"
            )
            await db.execute("DROP TABLE proxy_domains")
            await db.execute("ALTER TABLE proxy_domains_new RENAME TO proxy_domains")
            await db.commit()
        await db.execute("PRAGMA journal_mode=WAL")
        await db.commit()
        # Migration: add real_latency_ms to nodes if missing (real download latency via proxy)
        cursor = await db.execute("PRAGMA table_info(nodes)")
        rows = await cursor.fetchall()
        await cursor.close()
        if not any(r[1] == "real_latency_ms" for r in rows):
            await db.execute("ALTER TABLE nodes ADD COLUMN real_latency_ms INTEGER")
            await db.commit()


@asynccontextmanager
async def db_connection():
    """Async context manager for a DB connection with timeout (reduces 'database is locked' errors)."""
    db_path = await get_db_path()
    conn = await aiosqlite.connect(db_path, timeout=DB_TIMEOUT)
    try:
        yield conn
    finally:
        await conn.close()


async def get_connection():
    """Return a new DB connection (caller must close)."""
    db_path = await get_db_path()
    return await aiosqlite.connect(db_path, timeout=DB_TIMEOUT)
