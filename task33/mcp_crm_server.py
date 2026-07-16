"""MCP-сервер CRM поддержки (JSON-RPC over stdio).

Реализует минимальное подмножество Model Context Protocol на чистом stdlib,
чтобы сервер запускался на голом python3 без установки SDK. Поддерживает:
  * initialize
  * tools/list
  * tools/call
  * notifications/initialized (уведомление — ответа нет)

Инструменты: crm_user, crm_ticket, crm_user_tickets, crm_search.
Через них Claude Desktop/Code видит CRM поддержки как набор инструментов.

Проверка вручную:
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/call",
         "params":{"name":"crm_ticket","arguments":{"ticket_id":"T-1042"}}}' \
    | python3 mcp_crm_server.py
"""
from __future__ import annotations

import json
import sys

import crm_tools

SERVER_INFO = {"name": "support-assistant-crm", "version": "1.0.0"}

TOOLS = [
    {"name": "crm_user",
     "description": "Карточка пользователя CRM по id (тариф, роль, SSO, 2FA)",
     "inputSchema": {"type": "object",
                     "properties": {"user_id": {"type": "string",
                                                "description": "например U-100"}},
                     "required": ["user_id"]}},
    {"name": "crm_ticket",
     "description": "Карточка тикета поддержки по id, с перепиской",
     "inputSchema": {"type": "object",
                     "properties": {"ticket_id": {"type": "string",
                                                  "description": "например T-1042"}},
                     "required": ["ticket_id"]}},
    {"name": "crm_user_tickets",
     "description": "Все тикеты пользователя (свежие сверху)",
     "inputSchema": {"type": "object",
                     "properties": {"user_id": {"type": "string"}},
                     "required": ["user_id"]}},
    {"name": "crm_search",
     "description": "Поиск тикетов по подстроке в теме, коде ошибки и переписке",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "limit": {"type": "integer"}},
                     "required": ["query"]}},
]


def call_tool(name: str, args: dict) -> str:
    """Диспетчер инструментов: имя + аргументы → текст для модели."""
    crm = crm_tools.load_crm()

    if name == "crm_user":
        user_id = args.get("user_id")
        if not user_id:
            raise ValueError("crm_user: требуется аргумент user_id")
        return crm_tools.format_user(crm_tools.get_user(user_id, crm))

    if name == "crm_ticket":
        ticket_id = args.get("ticket_id")
        if not ticket_id:
            raise ValueError("crm_ticket: требуется аргумент ticket_id")
        return crm_tools.format_ticket(crm_tools.get_ticket(ticket_id, crm))

    if name == "crm_user_tickets":
        user_id = args.get("user_id")
        if not user_id:
            raise ValueError("crm_user_tickets: требуется аргумент user_id")
        tks = crm_tools.user_tickets(user_id, crm)
        if not tks:
            return f"У пользователя {user_id} нет тикетов."
        return "\n\n".join(crm_tools.format_ticket(t) for t in tks)

    if name == "crm_search":
        query = args.get("query")
        if not query:
            raise ValueError("crm_search: требуется аргумент query")
        hits = crm_tools.search_tickets(query, int(args.get("limit", 5)), crm)
        if not hits:
            return f"По запросу «{query}» тикетов не найдено."
        return "\n\n".join(crm_tools.format_ticket(t) for t in hits)

    raise ValueError(f"unknown tool: {name}")


def handle(req: dict) -> dict | None:
    """Один JSON-RPC запрос → ответ (или None для уведомлений)."""
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        result = {"protocolVersion": "2024-11-05",
                  "capabilities": {"tools": {}},
                  "serverInfo": SERVER_INFO}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = req.get("params", {})
        try:
            text = call_tool(params.get("name"), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": text}]}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": str(e)}}
    elif method in ("notifications/initialized",):
        return None  # уведомление без ответа
    else:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"method {method}"}}

    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
