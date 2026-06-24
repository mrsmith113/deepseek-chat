"""
Task 17 — Агент с remote MCP-сервером (Streamable HTTP)
Подключается к задеплоенному серверу на api.notifikatai.ru
"""

import asyncio
import json
import os
import httpx
from openai import AsyncOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# ── Настройки ──────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-key-here")
MCP_URL          = os.getenv("MCP_URL", "https://api1.notifikatai.ru/mcp")
MCP_TOKEN        = os.getenv("MCP_TOKEN", "change-me")

llm = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)

SYSTEM_PROMPT = """Ты — агент-ассистент с доступом к базе данных CouchDB.

У тебя есть инструменты для работы с CouchDB. Когда пользователь задаёт вопрос:
1. Реши, нужен ли инструмент
2. Если нужен — вызови его с правильными параметрами
3. Используй результат чтобы ответить пользователю на русском языке"""


def mcp_tools_to_openai(mcp_tools: list) -> list:
    """Конвертирует MCP tool definitions → формат OpenAI function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
    ]


async def run_agent(user_message: str, session: ClientSession, mcp_tools: list):
    """Один шаг агента: LLM → tool call → результат → финальный ответ."""

    openai_tools = mcp_tools_to_openai(mcp_tools)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ]

    print(f"\n👤 Пользователь: {user_message}")
    print("🤔 Агент думает...")

    # Шаг 1: LLM решает что делать
    response = await llm.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=openai_tools,
        tool_choice="auto",
        max_tokens=1000,
    )
    message = response.choices[0].message

    # Шаг 2: если LLM хочет вызвать инструмент
    if message.tool_calls:
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            print(f"🔧 Инструмент: {tool_name}")
            print(f"   Параметры: {json.dumps(tool_args, ensure_ascii=False)}")

            # Шаг 3: вызов MCP-инструмента на удалённом сервере
            tool_result = await session.call_tool(tool_name, tool_args)

            result_text = "".join(
                item.text for item in tool_result.content if hasattr(item, "text")
            )
            preview = result_text[:200] + ("..." if len(result_text) > 200 else "")
            print(f"📦 MCP ответ: {preview}")

            # Шаг 4: добавляем результат в диалог
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_call.function.arguments,
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_text,
            })

        # Шаг 5: LLM формулирует финальный ответ
        final = await llm.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=1000,
        )
        answer = final.choices[0].message.content
    else:
        answer = message.content

    print(f"\n🤖 Агент: {answer}")
    return answer


async def main():
    print("=" * 55)
    print("  Task 17 — Агент с remote MCP (CouchDB)")
    print("=" * 55)
    print(f"🔌 Подключаемся к {MCP_URL} ...")

    # headers передаются через httpx.AsyncClient
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {MCP_TOKEN}"},
        timeout=30,
    )

    async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP-соединение установлено")

            tools_result = await session.list_tools()
            mcp_tools = tools_result.tools
            print(f"🛠  Инструментов: {len(mcp_tools)}")
            for t in mcp_tools:
                print(f"   • {t.name} — {t.description}")

            print("\n" + "─" * 55)

            if os.getenv("DEMO_MODE") == "1":
                # Демо-режим для видео — три запроса подряд
                queries = [
                    "Какие базы данных есть в CouchDB?",
                    "Покажи документ с ID 'test_doc' из базы 'hornest'",
                    "Создай документ в базе 'hornest', ID='task17_result', данные: проект Hornest, задача 17, статус выполнено",
                ]
                for q in queries:
                    await run_agent(q, session, mcp_tools)
                    print("\n" + "─" * 55)
            else:
                # Интерактивный режим
                print("Введите запрос (или 'exit' для выхода)")
                print("─" * 55)
                while True:
                    try:
                        user_input = input("\n👤 Вы: ").strip()
                        if not user_input or user_input.lower() == "exit":
                            print("До свидания!")
                            break
                        await run_agent(user_input, session, mcp_tools)
                    except KeyboardInterrupt:
                        print("\nДо свидания!")
                        break


if __name__ == "__main__":
    asyncio.run(main())
