#!/usr/bin/env bash
# Ассистент разработчика (task32) — демо одной командой.
set -e
cd "$(dirname "$0")"

echo "== 1. Индексация документации (README + docs) =="
python3 indexer.py

echo
echo "== 2. MCP: список инструментов =="
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 mcp_server.py

echo
echo "== 3. MCP: текущая git-ветка =="
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"git_branch","arguments":{}}}' | python3 mcp_server.py

echo
echo "== 4. /help — вопрос о проекте =="
python3 assistant.py "как устроен RAG и какие режимы у CLI?"
