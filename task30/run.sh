#!/bin/bash
# Task 30 — Запуск LLM-сервиса
# Использует torch-env (там уже есть requests, fastapi если установить)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HOME/rag-env"
PORT=8030

echo "=== Task 30: Private LLM Service ==="
echo "Порт: $PORT (0.0.0.0 — доступен по сети)"
echo ""

# Активируем torch-env
source "$VENV/bin/activate"

# Устанавливаем зависимости если нужно
pip install fastapi uvicorn --quiet 2>/dev/null || true

echo "Запускаем сервис..."
echo "Веб-чат: http://$(hostname -I | awk '{print $1}'):$PORT"
echo "API docs: http://$(hostname -I | awk '{print $1}'):$PORT/docs"
echo ""

cd "$SCRIPT_DIR"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT" --log-level info
