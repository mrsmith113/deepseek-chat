"""
server.py — MCP-сервер Task 18 (Streamable HTTP, FastMCP)

Инструменты:
  get_stats(hours)       — статистика сбора за N часов
  get_digest(hours)      — запросить дайджест прямо сейчас
  force_collect()        — принудительный сбор постов
  set_schedule(job, min) — изменить интервал collect/digest
  list_channels()        — список каналов
  add_channel(username)  — добавить канал
  toggle_channel(u, on)  — вкл/выкл канал
"""

import os
import json
import asyncio
import logging
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

import db
import digest as digest_gen
import scheduler as sched

db.init_db()

MCP_TOKEN = os.environ["MCP_TOKEN"]
ALLOWED_HOST = os.getenv("ALLOWED_HOST", "127.0.0.1")


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
    "Challenge NewsBot Tools",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            ALLOWED_HOST,
            "127.0.0.1",
            "127.0.0.1:8001",
            "localhost",
            "localhost:8001",
        ],
        allowed_origins=[f"https://{ALLOWED_HOST}"],
    ),
)


@mcp.tool()
def get_stats(hours: int = 24) -> str:
    """Статистика сбора постов за последние N часов."""
    stats = db.get_stats(hours)
    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool()
def list_channels() -> str:
    """Список всех каналов (активных и неактивных)."""
    channels = db.get_channels(active_only=False)
    return json.dumps(channels, ensure_ascii=False, indent=2)


@mcp.tool()
def add_channel(username: str, title: str = "") -> str:
    """Добавить новый Telegram-канал для мониторинга."""
    ok = db.add_channel(username, title)
    if ok:
        return f"✅ Канал @{username.lstrip('@')} добавлен"
    return f"⚠️ Канал @{username.lstrip('@')} уже существует"


@mcp.tool()
def toggle_channel(username: str, active: bool) -> str:
    """Включить или выключить канал (active=true/false)."""
    ok = db.toggle_channel(username, active)
    state = "включён" if active else "выключен"
    if ok:
        return f"✅ Канал @{username.lstrip('@')} {state}"
    return f"❌ Канал @{username.lstrip('@')} не найден"


@mcp.tool()
def set_schedule(job: str, minutes: int) -> str:
    """
    Изменить интервал расписания.
    job: 'collect' или 'digest'
    minutes: интервал в минутах (минимум 5)
    """
    if minutes < 5:
        return "❌ Минимальный интервал — 5 минут"
    if job == "collect":
        sched.reschedule_collect(minutes)
        return f"✅ Сбор постов: каждые {minutes} мин"
    elif job == "digest":
        sched.reschedule_digest(minutes)
        return f"✅ Дайджест: каждые {minutes} мин"
    return f"❌ Неизвестный job: {job}. Используй 'collect' или 'digest'"


@mcp.tool()
async def force_collect() -> str:
    """Принудительно запустить сбор постов прямо сейчас."""
    await sched.collect_job()
    stats = db.get_stats(1)
    return f"✅ Сбор завершён. За последний час: {stats['total_posts']} постов"


@mcp.tool()
async def get_digest(hours: int = 24, tone: str = "black_humor") -> str:
    """
    Сгенерировать дайджест за последние N часов.
    tone: black_humor | neutral | hype
    """
    posts = db.get_unprocessed_posts(limit=20)
    if not posts:
        return "📭 Нет необработанных постов для дайджеста"

    ds_posts = [
        {"channel": p["channel"], "text": p["text"], "url": p["url"]}
        for p in posts
    ]
    result = await digest_gen.generate_digest(ds_posts, tone=tone)

    if not result:
        return "❌ DeepSeek не вернул результат"

    db.mark_processed([p["id"] for p in posts])
    formatted = digest_gen.format_digest_for_telegram(result)
    db.save_digest(len(posts), formatted, sent=False)
    return formatted


@mcp.tool()
def get_schedule() -> str:
    """Текущее расписание задач."""
    info = sched.get_schedule_info()
    collect_min = db.get_config("collect_interval_min", 60)
    digest_min = db.get_config("digest_interval_min", 360)
    lines = [
        f"⏱ Сбор постов: каждые {collect_min} мин",
        f"📰 Дайджест: каждые {digest_min} мин",
    ]
    for job_id, job in info.items():
        lines.append(f"  [{job_id}] следующий запуск: {job['next_run']}")
    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Запускаем планировщик (без Telegram-бота — только MCP)
    sched.start_scheduler()

    app = mcp.streamable_http_app()

    import starlette.middleware
    from starlette.applications import Starlette
    from starlette.routing import Mount

    wrapped = Starlette(
        routes=[Mount("/", app=app)],
    )
    wrapped.add_middleware(BearerAuthMiddleware)

    port = int(os.getenv("MCP_PORT", 8001))
    uvicorn.run(wrapped, host="127.0.0.1", port=port, log_level="info")
