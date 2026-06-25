"""
agent.py — демо-агент Task 18 с пошаговым трейсингом для видео
"""

import os
import sys
import asyncio
import json
import httpx
from datetime import datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MCP_URL = os.getenv("MCP_URL", "https://api1.notifikatai.ru/mcp-news")
MCP_TOKEN = os.environ["MCP_TOKEN"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.notifikatai.ru/api/deepseek")

PRINT_DELAY = float(os.getenv("PRINT_DELAY", "0.04"))
STEP_DELAY = float(os.getenv("STEP_DELAY", "1.2"))

DEMO_QUERIES = [
    "Покажи статистику за последние 24 часа",
    "Какие каналы сейчас мониторятся?",
    "Покажи расписание и последние посты",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def slow_print(text: str, delay: float = None):
    d = delay if delay is not None else PRINT_DELAY
    for ch in text:
        print(ch, end="", flush=True)
        if d > 0:
            await asyncio.sleep(d)
    print()


async def trace(icon: str, label: str, detail: str = ""):
    line = f"  {icon}  [{ts()}]  {label}"
    if detail:
        line += f"  →  {detail}"
    await slow_print(line)


async def separator(char="─", width=62):
    print(char * width)
    await asyncio.sleep(0.1)


async def print_box(title: str, char="█", width=62):
    pad = (width - len(title) - 2) // 2
    right_pad = width - pad - len(title) - 2
    print(f"\n{char * width}")
    print(f"{char * pad} {title} {char * right_pad}{char}")
    print(f"{char * width}\n")
    await asyncio.sleep(0.2)


# ── LLM через httpx ────────────────────────────────────────────────────────────

async def call_llm(messages: list, tools: list) -> dict:
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 1000,
        "temperature": 0.3,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ── Основной агент ─────────────────────────────────────────────────────────────

async def run_agent(user_query: str, session: ClientSession, query_num: int = 1):
    await print_box(f"ЗАПРОС #{query_num}")
    await trace("👤", "ПОЛЬЗОВАТЕЛЬ", user_query)
    await asyncio.sleep(STEP_DELAY)
    await separator()

    # Шаг 1 — получаем инструменты
    await trace("🔌", "MCP", f"запрашиваю список инструментов → {MCP_URL}")
    await asyncio.sleep(0.5)
    tools_result = await session.list_tools()
    tools_for_llm = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema if t.inputSchema else {"type": "object", "properties": {}},
            }
        }
        for t in tools_result.tools
    ]
    await trace("✅", "MCP", f"получено инструментов: {len(tools_for_llm)}")
    for t in tools_result.tools:
        await slow_print(f"       • {t.name}")
        await asyncio.sleep(0.05)

    await asyncio.sleep(STEP_DELAY * 0.5)
    await separator()

    await trace("🧠", "LLM (DeepSeek)", "отправляю запрос с набором инструментов...")

    messages = [
        {
            "role": "system",
            "content": (
                "Ты ассистент для управления AI-новостным ботом. "
                "Отвечаешь на русском. Используй инструменты для получения актуальных данных. "
                "После получения данных давай краткий, понятный ответ."
            )
        },
        {"role": "user", "content": user_query}
    ]

    step_num = 0

    for iteration in range(6):
        step_num += 1

        data = await call_llm(messages, tools_for_llm)
        choice = data["choices"][0]
        msg = choice["message"]
        finish = choice["finish_reason"]
        tool_calls = msg.get("tool_calls")

        messages.append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls,
        })

        await trace("💬", f"LLM ответ (шаг {step_num})", f"finish_reason={finish}")

        if not tool_calls:
            await separator()
            await trace("✨", "ФИНАЛЬНЫЙ ОТВЕТ", "")
            await separator()
            answer = msg.get("content") or "(пустой ответ)"
            for line in answer.split("\n"):
                await slow_print(f"  {line}", delay=PRINT_DELAY * 0.5)
            await separator()
            await asyncio.sleep(STEP_DELAY)
            break

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}

            await separator("·")
            await trace("🔧", "ВЫЗОВ ИНСТРУМЕНТА", fn_name)
            await trace("📤", "АРГУМЕНТЫ", json.dumps(fn_args, ensure_ascii=False) if fn_args else "(нет)")
            await trace("🌐", "MCP", f"отправляю tools/call → {fn_name}")
            await asyncio.sleep(0.4)

            try:
                result = await session.call_tool(fn_name, fn_args)
                content = result.content[0].text if result.content else "no result"
                ok = True
            except Exception as e:
                content = f"Error: {e}"
                ok = False

            status = "✅" if ok else "❌"
            await trace(status, "MCP ОТВЕТ", "получен")
            preview = content[:400].replace("\n", " ")
            if len(content) > 400:
                preview += "..."
            await slow_print(f"  📦  {preview}", delay=PRINT_DELAY * 0.3)
            await trace("🔄", "LLM", "передаю результат инструмента в контекст")
            await asyncio.sleep(STEP_DELAY * 0.5)

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": content,
            })

    await asyncio.sleep(STEP_DELAY)


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    demo_mode = os.getenv("DEMO_MODE") == "1"

    await print_box("CHALLENGE NEWSBOT — AGENT DEMO", char="█")
    await slow_print(f"  🕐  Старт: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    await slow_print(f"  🌐  MCP URL: {MCP_URL}")
    await slow_print(f"  🧠  LLM: DeepSeek Chat (через прокси)")
    await asyncio.sleep(STEP_DELAY)

    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {MCP_TOKEN}"},
        timeout=30.0,
    )

    await separator()
    await trace("🔗", "MCP CONNECT", f"подключаюсь к {MCP_URL}")

    async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await trace("🤝", "MCP HANDSHAKE", "initialize() — OK")
            await asyncio.sleep(STEP_DELAY)

            if demo_mode:
                for i, query in enumerate(DEMO_QUERIES, 1):
                    await run_agent(query, session, query_num=i)
                    if i < len(DEMO_QUERIES):
                        await slow_print(f"\n  ⏳  Пауза перед следующим запросом...\n")
                        await asyncio.sleep(2)
                await print_box("ДЕМО ЗАВЕРШЕНО", char="═")
            else:
                await separator()
                await slow_print("  Введи запрос (или 'exit' для выхода):\n")
                q_num = 1
                while True:
                    query = input("  👤 > ").strip()
                    if query.lower() in ("exit", "quit", "q", "выход"):
                        break
                    if query:
                        await run_agent(query, session, query_num=q_num)
                        q_num += 1


if __name__ == "__main__":
    if "--status" in sys.argv:
        from status import show_status
        asyncio.run(show_status())
    else:
        asyncio.run(main())
