# -*- coding: utf-8 -*-
"""
server.py - MCP Pipeline Server (Task 19)
Порт: 8002  |  Nginx: /mcp-pipeline
Транспорт: Streamable HTTP + Bearer Auth

Инструменты (пайплайн):
  search_posts(channel, hours)    - посты из SQLite Task18
  summarize_with_humor(text)      - DeepSeek, черный юмор
  save_to_file(content, filename) - файл на сервере
"""

import os
import json
import sqlite3
import httpx
import uvicorn
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.applications import Starlette
from starlette.routing import Mount

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── Конфиг ────────────────────────────────────────────────────────────────────

MCP_TOKEN    = os.environ["MCP_TOKEN"]
ALLOWED_HOST = os.getenv("ALLOWED_HOST", "127.0.0.1")
DEEPSEEK_KEY = os.environ["DEEPSEEK_KEY"]
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.notifikatai.ru/api/deepseek")

# Путь к базе бота Task18 — задаётся через .env
DB_PATH = Path(os.getenv("DB_PATH", "/opt/challenge-bot/challenge.db"))

SAVE_DIR = Path(os.getenv("SAVE_DIR", "/opt/mcp-pipeline/results"))
SAVE_DIR.mkdir(parents=True, exist_ok=True)


# ── Auth middleware ────────────────────────────────────────────────────────────

class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {MCP_TOKEN}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── MCP Server ─────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "Pipeline Tools",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            ALLOWED_HOST,
            "127.0.0.1",
            "127.0.0.1:8002",
            "localhost",
            "localhost:8002",
        ],
        allowed_origins=[f"https://{ALLOWED_HOST}"],
    ),
)


# ── Инструмент 1: SEARCH ───────────────────────────────────────────────────────

@mcp.tool()
def search_posts(channel: str, hours: int = 24) -> str:
    """Search posts from a Telegram channel stored in the local SQLite database.

    Args:
        channel: Telegram channel username (without @)
        hours: how many hours back to look (default 24)
    """
    channel = channel.lstrip("@")

    if not DB_PATH.exists():
        return f"[search_posts] DB not found: {DB_PATH}"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT channel, text, url, collected_at
           FROM raw_posts
           WHERE channel = ?
             AND collected_at >= datetime('now', ?)
           ORDER BY collected_at DESC
           LIMIT 20""",
        (channel, f"-{hours} hours"),
    ).fetchall()
    conn.close()

    if not rows:
        return f"[search_posts] No posts from @{channel} in the last {hours}h"

    lines = [f"Posts from @{channel} (last {hours}h): {len(rows)} found\n"]
    for i, row in enumerate(rows, 1):
        text = (row["text"] or "").strip().replace("\n", " ")
        if len(text) > 300:
            text = text[:300] + "..."
        lines.append(f"{i}. [{row['collected_at'][:16]}] {text}")
        if row["url"]:
            lines.append(f"   {row['url']}")
        lines.append("")

    return "\n".join(lines)


# ── Инструмент 2: SUMMARIZE WITH HUMOR ────────────────────────────────────────

@mcp.tool()
def summarize_with_humor(text: str, channel: str = "") -> str:
    """Summarize posts using DeepSeek with black humor tone, like a sarcastic colleague.

    Args:
        text: raw posts text to summarize
        channel: channel name for context (optional)
    """
    channel_note = f"@{channel.lstrip('@')}" if channel else "этот канал"

    system_prompt = (
        "Ты — циничный AI-аналитик с черным юмором. "
        "Тебе скармливают посты из Telegram-канала, а ты делаешь краткое саммари "
        "в стиле 'вчера он вещал о...' — саркастично, но информативно. "
        "Начни с фразы типа 'Вчера {channel} вещал о...' или 'Вчера {channel} открыл нам глаза на...'. "
        "2-4 предложения. Только русский язык."
    ).replace("{channel}", channel_note)

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 300,
                "temperature": 0.8,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()


# ── Инструмент 3: SAVE TO FILE ─────────────────────────────────────────────────

@mcp.tool()
def save_to_file(content: str, filename: str = "pipeline_result") -> str:
    """Save pipeline result to a file on the server.

    Args:
        content: text content to save
        filename: base filename without extension (default 'pipeline_result')
    """
    safe_name = filename.lstrip("@").replace(" ", "_").replace("/", "_")[:50] or "result"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = SAVE_DIR / f"{timestamp}_{safe_name}.txt"

    header = (
        f"# MCP Pipeline Result\n"
        f"# Saved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Source: {filename}\n"
        f"{'=' * 60}\n\n"
    )

    filepath.write_text(header + content, encoding="utf-8")

    size = len(content.encode("utf-8"))
    return f"Saved: {filepath}\nSize: {size} bytes"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = mcp.streamable_http_app()
    wrapped = Starlette(routes=[Mount("/", app=app)])
    wrapped.add_middleware(BearerAuthMiddleware)

    port = int(os.getenv("MCP_PORT", 8002))
    uvicorn.run(wrapped, host="127.0.0.1", port=port, log_level="info")
