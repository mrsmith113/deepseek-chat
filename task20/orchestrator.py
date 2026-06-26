# -*- coding: utf-8 -*-
"""
Task 20 — MCP Orchestration: LLM-based Multi-Server Router

Архитектура:
  ┌─────────────────────────────────────────────────────────┐
  │                   orchestrator.py                       │
  │                                                         │
  │  ┌──────────────┐        ┌─────────────────────────┐   │
  │  │ CouchDB MCP  │        │  Local Analysis MCP     │   │
  │  │ (HTTP remote)│        │  (stdio subprocess)     │   │
  │  │              │        │                         │   │
  │  │ list_dbs     │        │ analyze_text            │   │
  │  │ get_document │        │ create_summary          │   │
  │  │ save_document│        │ format_document         │   │
  │  └──────────────┘        └─────────────────────────┘   │
  │          ↑                          ↑                   │
  │          └──────────────────────────┘                   │
  │                   Tool Registry                         │
  │                   (unified map)                         │
  │                        ↑                                │
  │                  DeepSeek Router                        │
  │           (ReAct loop: Think → Route → Execute)         │
  └─────────────────────────────────────────────────────────┘

Запуск:
    python orchestrator.py
    python orchestrator.py "свой запрос в кавычках"
"""

import asyncio
import json
import os
import re
import sys
import time

import httpx
from contextlib import AsyncExitStack
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters

# Ищем .env: сначала рядом со скриптом, потом поднимаемся вверх по дереву
def _find_dotenv() -> str | None:
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(current, ".env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None

_env_path = _find_dotenv()
if _env_path:
    load_dotenv(_env_path)
    print(f"  [env] Загружен: {_env_path}")
else:
    load_dotenv()  # fallback — стандартный поиск

# ─── Конфигурация ────────────────────────────────────────────────────────────

DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.notifikatai.ru/api/deepseek")

if not DEEPSEEK_KEY:
    print("❌  DEEPSEEK_KEY не задан. Создайте .env с DEEPSEEK_KEY=... в папке проекта или выше.")
    sys.exit(1)

# Server 1: Remote CouchDB (Task 17)
COUCHDB_URL   = "https://api1.notifikatai.ru/mcp"
COUCHDB_TOKEN = "hornest-mcp-2026"

# Server 2: Local stdio (local_server.py)
LOCAL_SERVER_PATH = os.path.join(os.path.dirname(__file__), "local_server.py")

# Демо-задача — упражняет все 5 шагов через оба сервера
DEFAULT_TASK = (
    "Проанализируй текст, создай саркастическое саммари, отформатируй как документ "
    "и сохрани в CouchDB в базу 'research' (если такой нет — используй любую доступную). "
    "\n\nТекст:\n"
    "«В 2025 году каждый стартап называет свой чат-бот агентом. "
    "Настоящий агент автономно использует инструменты, планирует действия и достигает цели "
    "без постоянного участия человека. "
    "Model Context Protocol (MCP) стандартизирует подключение инструментов к LLM, "
    "превращая разрозненные API в единую экосистему. "
    "Мультиагентные системы позволяют решать задачи, которые раньше требовали целой команды.»"
)

MAX_STEPS = 12  # защита от бесконечного цикла

# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Ты — AI-оркестратор с доступом к инструментам на нескольких MCP-серверах.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools}

ФОРМАТ ВЫВОДА — только валидный JSON, без markdown, без лишнего текста:

Вызов инструмента:
{{"thinking": "объяснение на русском: почему именно этот инструмент сейчас", "server": "<server>", "action": "<tool_name>", "args": {{...}}}}

Финальный ответ (когда задача полностью выполнена):
{{"thinking": "итоговое объяснение", "action": "FINAL", "answer": "краткий итог на русском"}}

ПРАВИЛА:
1. Используй результаты предыдущих шагов в следующих вызовах.
2. server должен быть строго одним из: {server_names}
3. Не повторяй вызовы с теми же аргументами.
4. Поле "thinking" всегда на русском языке.
5. Выводи ТОЛЬКО JSON — ничего больше.
"""

# ─── DeepSeek ────────────────────────────────────────────────────────────────

def call_deepseek(messages: list) -> str:
    """Synchronous DeepSeek call (runs in executor from async context)."""
    # Поддерживаем оба формата URL:
    # прямой DeepSeek: https://api.deepseek.com/v1/chat/completions
    # прокси:          https://api.notifikatai.ru/api/deepseek
    url = DEEPSEEK_URL
    if not url.endswith("/chat/completions") and "deepseek.com" in url:
        url = url.rstrip("/") + "/chat/completions"

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "max_tokens": 600,
                "temperature": 0.15,  # низкая температура → стабильный JSON
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def extract_json(text: str) -> dict:
    """Parse JSON from LLM response with multiple fallback strategies."""
    # 1. Прямой парсинг
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Убираем markdown-фенсы
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 3. Ищем первый блок {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Cannot parse JSON:\n{text[:300]}")

# ─── Tool Registry ────────────────────────────────────────────────────────────

def build_tools_desc(registry: dict) -> str:
    """Build human-readable tool list for the system prompt."""
    lines = []
    for name, entry in registry.items():
        tool   = entry["tool"]
        server = entry["server"]
        props  = (tool.inputSchema or {}).get("properties", {})
        params = ", ".join(props.keys()) or "—"
        desc   = (tool.description or "").split("\n")[0]  # первая строка
        lines.append(f"  [{server}] {name}({params})\n    → {desc}")
    return "\n".join(lines)

# ─── Pretty Print ─────────────────────────────────────────────────────────────

def hline(char: str = "─", width: int = 62) -> str:
    return char * width

def print_header():
    print()
    print("╔" + "═" * 60 + "╗")
    print("║  MCP ORCHESTRATOR — TASK 20" + " " * 32 + "║")
    print("║  LLM Router: DeepSeek → Multi-Server Tool Selection  ║")
    print("╚" + "═" * 60 + "╝")

def print_step(n: int, thinking: str, server: str, action: str, args: dict):
    print(f"\n{hline()}")
    print(f"  🔄 ШАГ {n}  [{server}]  →  {action}")
    thinking_short = thinking[:90] + ("..." if len(thinking) > 90 else "")
    print(f"  💭 {thinking_short}")
    args_str = json.dumps(args, ensure_ascii=False)
    if len(args_str) > 80:
        args_str = args_str[:80] + "..."
    print(f"  📥 {args_str}")

def print_result(text: str, elapsed: float):
    preview = text[:250].replace("\n", " ")
    suffix  = "..." if len(text) > 250 else ""
    print(f"  ✓ ({elapsed:.1f}s)  {preview}{suffix}")

def print_final(n_steps: int, elapsed: float, answer: str):
    print(f"\n{'═' * 62}")
    print(f"  ✅  ЗАВЕРШЕНО  |  {n_steps} шагов  |  {elapsed:.1f}s")
    print(f"{'═' * 62}")
    print(f"\n  📋  Итог:\n  {answer}\n")

# ─── Orchestrator Loop ────────────────────────────────────────────────────────

async def orchestrate(sessions: dict, registry: dict, task: str) -> None:
    """ReAct loop: Think (LLM) → Route → Execute → Repeat."""

    tools_desc   = build_tools_desc(registry)
    server_names = " | ".join(sessions.keys())

    system = SYSTEM_PROMPT.format(tools=tools_desc, server_names=server_names)
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": task},
    ]

    print(f"\n  🎯 Задача:\n  {task[:120]}{'...' if len(task) > 120 else ''}")
    print(f"\n  🔧 Серверов: {len(sessions)}  |  Инструментов: {len(registry)}")
    print(f"  🗂  Реестр: {list(registry.keys())}\n")

    t_start = time.time()
    loop = asyncio.get_event_loop()

    for step in range(1, MAX_STEPS + 1):
        print(f"  ⏳ DeepSeek думает (шаг {step})...")

        # Запускаем синхронный вызов DeepSeek в executor, чтобы не блокировать event loop
        raw = await loop.run_in_executor(None, call_deepseek, messages)

        try:
            decision = extract_json(raw)
        except ValueError as exc:
            print(f"  ❌ JSON parse error: {exc}")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"[ERROR] Ответ не является валидным JSON. Повтори в правильном формате."})
            continue

        action   = decision.get("action", "")
        thinking = decision.get("thinking", "")

        # ── Финал ──────────────────────────────────────────────
        if action == "FINAL":
            print_final(step, time.time() - t_start, decision.get("answer", ""))
            return

        # ── Вызов инструмента ──────────────────────────────────
        server = decision.get("server", "")
        args   = decision.get("args", {})

        print_step(step, thinking, server, action, args)

        # Валидация: инструмент существует?
        if action not in registry:
            known = list(registry.keys())
            err   = f"[ERROR] Инструмент '{action}' не найден. Доступны: {known}"
            print(f"  ❌ {err}")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": err})
            continue

        # Валидация: сервер совпадает с реестром?
        actual_server = registry[action]["server"]
        if server != actual_server:
            print(f"  ⚠️  Маршрут скорректирован: {server!r} → {actual_server!r}")
            server = actual_server

        session = registry[action]["session"]

        # Вызов инструмента
        t_call = time.time()
        try:
            result      = await session.call_tool(action, args)
            result_text = result.content[0].text if result.content else "(empty result)"
            print_result(result_text, time.time() - t_call)
        except Exception as exc:
            result_text = f"[TOOL ERROR] {exc}"
            print(f"  ❌ {exc}")

        # Добавляем в историю
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role":    "user",
            "content": f"[Результат {action}]\n{result_text}",
        })

    print(f"\n  ⚠️  Достигнут лимит шагов ({MAX_STEPS})")

# ─── Server Setup ─────────────────────────────────────────────────────────────

async def connect_servers(stack: AsyncExitStack) -> tuple[dict, dict]:
    """
    Подключается к обоим серверам, возвращает:
        sessions  = {server_name: ClientSession}
        registry  = {tool_name: {"session": ..., "server": ..., "tool": ...}}
    """
    sessions = {}
    registry = {}

    print("\n  📡 Подключение к MCP-серверам...")

    # ── Server 1: Remote CouchDB (Streamable HTTP) ──────────────────────────
    try:
        http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {COUCHDB_TOKEN}"},
            timeout=30.0,
        )
        r, w, _ = await stack.enter_async_context(
            streamable_http_client(COUCHDB_URL, http_client=http_client)
        )
        session = await stack.enter_async_context(ClientSession(r, w))
        await session.initialize()

        tools_resp = await session.list_tools()
        for t in tools_resp.tools:
            registry[t.name] = {"session": session, "server": "couchdb", "tool": t}

        sessions["couchdb"] = session
        tool_names = [t.name for t in tools_resp.tools]
        print(f"  ✓  couchdb  [{COUCHDB_URL}]")
        print(f"     Инструменты: {tool_names}")

    except Exception as exc:
        print(f"  ✗  couchdb: {exc}")

    # ── Server 2: Local stdio ─────────────────────────────────────────────────
    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=[LOCAL_SERVER_PATH],
            env={**os.environ},
        )
        r, w = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(r, w))
        await session.initialize()

        tools_resp = await session.list_tools()
        for t in tools_resp.tools:
            registry[t.name] = {"session": session, "server": "local", "tool": t}

        sessions["local"] = session
        tool_names = [t.name for t in tools_resp.tools]
        print(f"  ✓  local  [stdio → {os.path.basename(LOCAL_SERVER_PATH)}]")
        print(f"     Инструменты: {tool_names}")

    except Exception as exc:
        print(f"  ✗  local: {exc}")

    return sessions, registry

# ─── Entry Point ─────────────────────────────────────────────────────────────

async def main(task: str) -> None:
    print_header()

    async with AsyncExitStack() as stack:
        sessions, registry = await connect_servers(stack)

        if not sessions:
            print("\n  ❌ Нет доступных серверов. Выход.")
            return

        if not registry:
            print("\n  ❌ Нет доступных инструментов. Выход.")
            return

        await orchestrate(sessions, registry, task)


if __name__ == "__main__":
    raw_args = sys.argv[1:]
    task = " ".join(raw_args).strip() if raw_args else DEFAULT_TASK
    asyncio.run(main(task))
