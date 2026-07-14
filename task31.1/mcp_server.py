"""MCP-сервер git-контекста (JSON-RPC over stdio).

Реализует минимальное подмножество Model Context Protocol на чистом stdlib,
чтобы сервер запускался на голом python3 без установки SDK. Поддерживает:
  * initialize
  * tools/list
  * tools/call

Инструменты: git_branch (минимум задания), git_files, git_diff.

Проверка вручную:
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/call",
         "params":{"name":"git_branch","arguments":{}}}' | python3 mcp_server.py
"""
from __future__ import annotations

import json
import sys

import git_tools

SERVER_INFO = {"name": "dev-assistant-git", "version": "1.0.0"}

TOOLS = [
    {"name": "git_branch",
     "description": "Текущая git-ветка репозитория проекта",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "git_files",
     "description": "Список файлов под контролем git",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer"}}}},
    {"name": "git_diff",
     "description": "Unified diff (--stat) рабочего дерева",
     "inputSchema": {"type": "object",
                     "properties": {"staged": {"type": "boolean"}}}},
]


def call_tool(name: str, args: dict) -> str:
    if name == "git_branch":
        return git_tools.git_branch()
    if name == "git_files":
        return git_tools.git_files(int(args.get("limit", 60)))
    if name == "git_diff":
        return git_tools.git_diff(bool(args.get("staged", False)))
    raise ValueError(f"unknown tool: {name}")


def handle(req: dict) -> dict | None:
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
