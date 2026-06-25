"""
db.py — SQLite-обёртка для Task 18
Таблицы: channels, raw_posts, digest_log, app_config
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "challenge.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            title       TEXT,
            active      INTEGER DEFAULT 1,
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS raw_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            channel     TEXT NOT NULL,
            post_id     INTEGER NOT NULL,
            text        TEXT,
            url         TEXT,
            collected_at TEXT DEFAULT (datetime('now')),
            processed   INTEGER DEFAULT 0,
            UNIQUE(channel, post_id)
        );

        CREATE TABLE IF NOT EXISTS digest_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now')),
            posts_count INTEGER,
            result      TEXT,
            sent        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS app_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        INSERT OR IGNORE INTO app_config(key, value) VALUES
            ('collect_interval_min', '60'),
            ('digest_interval_min', '360'),
            ('digest_tone', 'black_humor'),
            ('last_collect', ''),
            ('last_digest', '');

        INSERT OR IGNORE INTO channels(username, title) VALUES
            ('sergeinotevskii', 'Сергей Нотевский'),
            ('alexgladkovblog', 'Алекс Гладков'),
            ('aostrikov_ai_agents', 'Острикова AI Agents');
        """)


# ── channels ──────────────────────────────────────────────────────────────────

def get_channels(active_only=True) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM channels"
        if active_only:
            q += " WHERE active = 1"
        return [dict(r) for r in conn.execute(q).fetchall()]


def add_channel(username: str, title: str = "") -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO channels(username, title) VALUES (?, ?)",
                (username.lstrip("@"), title or username)
            )
        return True
    except sqlite3.IntegrityError:
        return False  # уже есть


def toggle_channel(username: str, active: bool) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE channels SET active=? WHERE username=?",
            (1 if active else 0, username.lstrip("@"))
        )
        return cur.rowcount > 0


def delete_channel(username: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM channels WHERE username=?",
            (username.lstrip("@"),)
        )
        return cur.rowcount > 0


# ── raw_posts ──────────────────────────────────────────────────────────────────

def save_post(channel: str, post_id: int, text: str, url: str) -> bool:
    """Сохраняет пост. Возвращает True если новый."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO raw_posts(channel, post_id, text, url) VALUES (?,?,?,?)",
                (channel, post_id, text, url)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_unprocessed_posts(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM raw_posts WHERE processed=0 ORDER BY collected_at LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_processed(post_ids: list[int]):
    if not post_ids:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE raw_posts SET processed=1 WHERE id IN ({','.join('?'*len(post_ids))})",
            post_ids
        )


def get_stats(hours: int = 24) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM raw_posts WHERE collected_at >= datetime('now', ?)",
            (f"-{hours} hours",)
        ).fetchone()[0]
        processed = conn.execute(
            "SELECT COUNT(*) FROM raw_posts WHERE processed=1 AND collected_at >= datetime('now', ?)",
            (f"-{hours} hours",)
        ).fetchone()[0]
        by_channel = conn.execute(
            """SELECT channel, COUNT(*) as cnt FROM raw_posts
               WHERE collected_at >= datetime('now', ?)
               GROUP BY channel""",
            (f"-{hours} hours",)
        ).fetchall()
        digests = conn.execute(
            "SELECT COUNT(*) FROM digest_log WHERE created_at >= datetime('now', ?)",
            (f"-{hours} hours",)
        ).fetchone()[0]
        return {
            "hours": hours,
            "total_posts": total,
            "processed_posts": processed,
            "pending_posts": total - processed,
            "digests_sent": digests,
            "by_channel": {r["channel"]: r["cnt"] for r in by_channel},
        }


# ── digest_log ─────────────────────────────────────────────────────────────────

def save_digest(posts_count: int, result: str, sent: bool = False) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO digest_log(posts_count, result, sent) VALUES (?,?,?)",
            (posts_count, result, 1 if sent else 0)
        )
        return cur.lastrowid


def get_recent_digests(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM digest_log ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── app_config ─────────────────────────────────────────────────────────────────

def get_config(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
        return row[0] if row else default


def set_config(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_config(key, value) VALUES (?,?)",
            (key, str(value))
        )
