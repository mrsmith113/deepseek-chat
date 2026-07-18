"""MCP-сервер файлового ассистента проекта (JSON-RPC over stdio).

Реализует минимальное подмножество Model Context Protocol на чистом stdlib,
чтобы сервер запускался на голом python3 без установки SDK. Поддерживает:
  * initialize
  * tools/list
  * tools/call
  * notifications/initialized (уведомление — ответа нет)

Инструменты: fs_list, fs_read, fs_grep, fs_write, fs_diff.
Через них Claude Desktop/Code видит папку project/ как набор инструментов:
может смотреть дерево, читать, искать регуляркой и править файлы —
но только внутри песочницы (см. fs_tools._safe).

Проверка вручную:
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/call",
         "params":{"name":"fs_grep","arguments":{"pattern":"def ","glob":"*.py"}}}' \
    | python3 mcp_fs_server.py

  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp_fs_server.py
"""
from __future__ import annotations

import json
import sys

import fs_tools

SERVER_INFO = {"name": "project-files-assistant", "version": "1.0.0"}

TOOLS = [
    {"name": "fs_list",
     "description": "Список файлов проекта (рекурсивно). Начинай с него, "
                    "чтобы понять структуру, прежде чем читать или править",
     "inputSchema": {"type": "object",
                     "properties": {"subdir": {"type": "string",
                                               "description": "подпапка, "
                                                              "по умолчанию весь проект"}},
                     "required": []}},
    {"name": "fs_read",
     "description": "Прочитать файл проекта целиком",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string",
                                             "description": "путь от корня проекта, "
                                                            "например utils.py"}},
                     "required": ["path"]}},
    {"name": "fs_grep",
     "description": "Поиск по файлам регулярным выражением (регистронезависимо). "
                    "Быстрый способ найти, где что определено и кто это зовёт",
     "inputSchema": {"type": "object",
                     "properties": {"pattern": {"type": "string",
                                                "description": "regex, например def .*retry"},
                                    "glob": {"type": "string",
                                             "description": "фильтр файлов, "
                                                            "например *.py (по умолчанию все)"}},
                     "required": ["pattern"]}},
    {"name": "fs_write",
     "description": "Записать файл (создаёт новый или заменяет содержимое целиком). "
                    "С dry_run=true ничего не пишет, только показывает будущий diff",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string",
                                             "description": "путь от корня проекта"},
                                    "content": {"type": "string",
                                                "description": "новое содержимое файла целиком"},
                                    "dry_run": {"type": "boolean",
                                                "description": "true — только показать diff, "
                                                               "не записывать"}},
                     "required": ["path", "content"]}},
    {"name": "fs_diff",
     "description": "Показать unified diff между текущим содержимым файла "
                    "и предлагаемым — без записи на диск",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "new_content": {"type": "string"}},
                     "required": ["path", "new_content"]}},
]


def call_tool(name: str, args: dict) -> str:
    """Диспетчер инструментов: имя + аргументы → текст для модели."""
    if name == "fs_list":
        files = fs_tools.fs_list(args.get("subdir") or ".")
        return fs_tools.format_list(files)

    if name == "fs_read":
        path = args.get("path")
        if not path:
            raise ValueError("fs_read: требуется аргумент path")
        return fs_tools.fs_read(path)

    if name == "fs_grep":
        pattern = args.get("pattern")
        if not pattern:
            raise ValueError("fs_grep: требуется аргумент pattern")
        hits = fs_tools.fs_grep(pattern, args.get("glob") or "*")
        return fs_tools.format_grep(hits)

    if name == "fs_write":
        path = args.get("path")
        content = args.get("content")
        if not path:
            raise ValueError("fs_write: требуется аргумент path")
        if content is None:
            raise ValueError("fs_write: требуется аргумент content")
        res = fs_tools.fs_write(path, content, bool(args.get("dry_run", False)))
        return _format_write(res)

    if name == "fs_diff":
        path = args.get("path")
        new_content = args.get("new_content")
        if not path:
            raise ValueError("fs_diff: требуется аргумент path")
        if new_content is None:
            raise ValueError("fs_diff: требуется аргумент new_content")
        diff = fs_tools.fs_diff(path, new_content)
        return diff or f"{path}: изменений нет."

    raise ValueError(f"unknown tool: {name}")


def _format_write(res: dict) -> str:
    """Краткий отчёт о записи + diff — то, что увидит модель."""
    if not res["changed"]:
        return f"{res['path']}: изменений нет, файл не тронут."

    if res["dry_run"]:
        head = (f"{res['path']}: предпросмотр (dry_run), на диск НЕ записано. "
                f"{'Файл будет создан.' if res['created'] else 'Файл будет изменён.'}")
    else:
        head = (f"{res['path']}: "
                f"{'создан' if res['created'] else 'изменён'}.")
    return f"{head}\n\n{res['diff']}"


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
