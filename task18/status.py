"""
status.py — живой статус системы для видео
Дёргает MCP (статистика, каналы, расписание) + SSH (systemd статус сервисов)
"""

import os
import asyncio
import json
import httpx
from datetime import datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
MCP_URL = os.getenv("MCP_URL", "https://api1.notifikatai.ru/mcp-news")
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")
PRINT_DELAY = float(os.getenv("PRINT_DELAY", "0.03"))

# SSH для проверки systemd (опционально — если не задан, пропускаем)
SSH_HOST = os.getenv("SSH_HOST", "82.21.53.191")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_KEY  = os.getenv("SSH_KEY", "")   # путь к ключу, например ~/.ssh/id_ed25519


# ── Helpers ────────────────────────────────────────────────────────────────────

async def slow_print(text: str, delay: float = None):
    d = delay if delay is not None else PRINT_DELAY
    for ch in text:
        print(ch, end="", flush=True)
        if d > 0:
            await asyncio.sleep(d)
    print()


async def separator(char="─", width=62):
    print(char * width, flush=True)
    await asyncio.sleep(0.05)


async def print_box(title: str, char="█", width=62):
    pad = (width - len(title) - 2) // 2
    right_pad = width - pad - len(title) - 2
    print(f"\n{char * width}")
    print(f"{char * pad} {title} {char * right_pad}{char}")
    print(f"{char * width}\n")
    await asyncio.sleep(0.2)


# ── SSH статус systemd ─────────────────────────────────────────────────────────

async def get_service_status(service: str) -> dict:
    """
    Проверяет статус systemd-сервиса через SSH.
    Возвращает {running, pid, uptime, status_line}
    """
    if not SSH_HOST:
        return {"running": None, "pid": "?", "uptime": "?", "status_line": "SSH не настроен"}

    key_arg = f"-i {SSH_KEY}" if SSH_KEY else ""
    cmd = (
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
        f"{key_arg} {SSH_USER}@{SSH_HOST} "
        f"\"systemctl show {service} --property=ActiveState,MainPID,ActiveEnterTimestamp 2>/dev/null\""
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        output = stdout.decode().strip()

        props = {}
        for line in output.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        active = props.get("ActiveState", "unknown")
        pid = props.get("MainPID", "?")
        start_ts = props.get("ActiveEnterTimestamp", "")

        # считаем uptime
        uptime_str = "?"
        if start_ts and start_ts != "n/a":
            try:
                # формат: "Thu 2026-06-24 12:00:00 UTC"
                parts = start_ts.split()
                if len(parts) >= 3:
                    dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
                    delta = datetime.utcnow() - dt
                    h, rem = divmod(int(delta.total_seconds()), 3600)
                    m = rem // 60
                    uptime_str = f"{h}ч {m}м"
            except Exception:
                uptime_str = "?"

        return {
            "running": active == "active",
            "pid": pid,
            "uptime": uptime_str,
            "status_line": active,
        }
    except asyncio.TimeoutError:
        return {"running": None, "pid": "?", "uptime": "?", "status_line": "timeout"}
    except Exception as e:
        return {"running": None, "pid": "?", "uptime": "?", "status_line": str(e)}


# ── MCP данные ─────────────────────────────────────────────────────────────────

async def get_mcp_data(session: ClientSession) -> dict:
    """Собирает stats + channels + schedule через MCP."""
    results = {}

    # stats
    try:
        r = await session.call_tool("get_stats", {"hours": 24})
        results["stats"] = json.loads(r.content[0].text)
    except Exception as e:
        results["stats"] = {"error": str(e)}

    # channels
    try:
        r = await session.call_tool("list_channels", {})
        results["channels"] = json.loads(r.content[0].text)
    except Exception as e:
        results["channels"] = []

    # schedule
    try:
        r = await session.call_tool("get_schedule", {})
        results["schedule_text"] = r.content[0].text
    except Exception as e:
        results["schedule_text"] = f"ошибка: {e}"

    return results


# ── Рендер статуса ─────────────────────────────────────────────────────────────

async def render_status(services: dict, mcp_data: dict):
    now = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")

    await print_box("CHALLENGE NEWSBOT — LIVE STATUS")
    await slow_print(f"  🕐  {now}")
    await slow_print(f"  🌐  Сервер: {SSH_HOST}")
    await slow_print(f"  🔗  MCP:    {MCP_URL}")
    print()

    # ── Сервисы ──
    await separator()
    await slow_print("  СЕРВИСЫ (systemd)")
    await separator()

    for name, info in services.items():
        if info["running"] is True:
            icon = "🟢"
            state = f"RUNNING   pid={info['pid']}   uptime={info['uptime']}"
        elif info["running"] is False:
            icon = "🔴"
            state = f"STOPPED   ({info['status_line']})"
        else:
            icon = "🟡"
            state = f"UNKNOWN   ({info['status_line']})"
        await slow_print(f"  {icon}  {name:<30} {state}")

    print()

    # ── Каналы ──
    await separator()
    await slow_print("  КАНАЛЫ (мониторинг)")
    await separator()

    channels = mcp_data.get("channels", [])
    if channels:
        active = [c for c in channels if c.get("active")]
        inactive = [c for c in channels if not c.get("active")]
        for ch in active:
            await slow_print(f"  ✅  @{ch['username']:<30} активен")
        for ch in inactive:
            await slow_print(f"  ⏸   @{ch['username']:<30} выключен")
        print()
        await slow_print(f"  Итого: {len(active)} активных / {len(channels)} всего")
    else:
        await slow_print("  (нет данных)")

    print()

    # ── Планировщик ──
    await separator()
    await slow_print("  ПЛАНИРОВЩИК (APScheduler)")
    await separator()

    schedule_text = mcp_data.get("schedule_text", "")
    for line in schedule_text.splitlines():
        await slow_print(f"  {line.strip()}")

    print()

    # ── Статистика ──
    await separator()
    await slow_print("  СТАТИСТИКА (последние 24ч)")
    await separator()

    stats = mcp_data.get("stats", {})
    if "error" not in stats:
        await slow_print(f"  📥  Постов собрано:      {stats.get('total_posts', '?')}")
        await slow_print(f"  ✅  Обработано:          {stats.get('processed_posts', '?')}")
        await slow_print(f"  ⏳  В очереди:           {stats.get('pending_posts', '?')}")
        await slow_print(f"  📰  Дайджестов отправлено: {stats.get('digests_sent', '?')}")

        by_channel = stats.get("by_channel", {})
        if by_channel:
            print()
            await slow_print("  По каналам:")
            for ch, cnt in by_channel.items():
                await slow_print(f"       • @{ch:<28} {cnt} постов")
    else:
        await slow_print(f"  ❌  Ошибка: {stats['error']}")

    print()
    await separator("═")
    await slow_print("  Статус получен. Система работает в штатном режиме 24/7.")
    await separator("═")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

async def show_status():
    await slow_print("\n  ⏳  Собираю данные о системе...", delay=0.02)
    print()

    # Параллельно: SSH статусы сервисов
    service_names = ["challenge-bot", "challenge-mcp"]
    service_tasks = {name: get_service_status(name) for name in service_names}
    service_results_raw = await asyncio.gather(*service_tasks.values(), return_exceptions=True)
    services = {}
    for name, result in zip(service_tasks.keys(), service_results_raw):
        if isinstance(result, Exception):
            services[name] = {"running": None, "pid": "?", "uptime": "?", "status_line": str(result)}
        else:
            services[name] = result

    # MCP данные
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {MCP_TOKEN}"},
        timeout=15.0,
    )

    try:
        async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_data = await get_mcp_data(session)
    except Exception as e:
        mcp_data = {"error": str(e), "channels": [], "stats": {}, "schedule_text": f"MCP недоступен: {e}"}

    await render_status(services, mcp_data)


if __name__ == "__main__":
    asyncio.run(show_status())
