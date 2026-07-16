#!/bin/bash
# Демо ассистента поддержки (task33) — офлайн, одной командой.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo "== 1. Строю RAG-индекс базы знаний (docs/*.md) =="
$PY indexer.py

echo
echo "== 2. Проверяю MCP-сервер CRM (crm_ticket T-1042) =="
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"crm_ticket","arguments":{"ticket_id":"T-1042"}}}' | $PY mcp_crm_server.py

echo
echo "== 3. Ответ на тикет T-1042 =="
$PY support.py --ticket T-1042 --question "Почему не работает авторизация?" --out answer.md
echo
cat answer.md
