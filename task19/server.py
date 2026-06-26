# -*- coding: utf-8 -*-
import os
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

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MCP_TOKEN    = os.getenv("MCP_TOKEN", "pipeline-mcp-2026")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.notifikatai.ru/api/deepseek")
DB_PATH  = Path(os.getenv("DB_PATH",  "/opt/challenge-bot/challenge.db"))
SAVE_DIR = Path(os.getenv("SAVE_DIR", "/opt/mcp-pipeline/results"))
SAVE_DIR.mkdir(parents=True, exist_ok=True)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != MCP_TOKEN:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


mcp = FastMCP(
    "Pipeline Tools",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def search_posts(channel: str, hours: int = 24) -> str:
    """Search posts from a Telegram channel in local SQLite database.

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
        "SELECT channel, text, url, collected_at FROM raw_posts "
        "WHERE channel = ? AND collected_at >= datetime('now', ?) "
        "ORDER BY collected_at DESC LIMIT 20",
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


@mcp.tool()
def summarize_with_humor(text: str, channel: str = "") -> str:
    """Summarize posts with DeepSeek using black humor tone.

    Args:
        text: raw posts text to summarize
        channel: channel name for context (optional)
    """
    channel_note = f"@{channel.lstrip('@')}" if channel else "etot kanal"
    system_prompt = (
        "Ty - cinichnyy AI-analitik s chernym yumorom. "
        "Tebe skarmlivayut posty iz Telegram-kanala, a ty delaesh kratkoe sammari "
        "v stile 'vchera on veshchal o...' - sarkastichno, no informativno. "
        "Nachni s 'Vchera {channel} veshchal o...' ili 'Vchera {channel} otkryl nam glaza na...'. "
        "2-4 predlozheniya. Tolko russkiy yazyk."
    ).replace("{channel}", channel_note)
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
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
    return resp.json()["choices"][0]["message"]["content"].strip()


@mcp.tool()
def save_to_file(content: str, filename: str = "pipeline_result") -> str:
    """Save pipeline result to a file on the server.

    Args:
        content: text content to save
        filename: base filename without extension
    """
    safe_name = filename.lstrip("@").replace(" ", "_").replace("/", "_")[:50] or "result"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = SAVE_DIR / f"{timestamp}_{safe_name}.txt"
    filepath.write_text(
        f"# MCP Pipeline Result\n# Saved: {datetime.now()}\n# Source: {filename}\n{'='*60}\n\n" + content,
        encoding="utf-8"
    )
    return f"Saved: {filepath}\nSize: {len(content.encode('utf-8'))} bytes"


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    port = int(os.getenv("MCP_PORT", 8002))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
