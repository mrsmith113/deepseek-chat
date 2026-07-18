#!/bin/bash
# Демо файлового ассистента (task34) — офлайн, одной командой.
# Идемпотентно: повторный прогон даёт тот же результат.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo "== 1. Smoke-тесты файлового ядра =="
$PY test_fs_tools.py

echo
echo "== 2. Проверяю MCP-сервер (tools/list) =="
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | $PY mcp_fs_server.py \
  | $PY -c '
import json, sys
tools = json.load(sys.stdin)["result"]["tools"]
print("MCP отдал %d инструментов:" % len(tools))
for t in tools:
    print("  - %-8s %s..." % (t["name"], t["description"][:58]))
'

echo
echo "== 3. Сценарий 1: поиск использования ApiClient =="
$PY main.py --goal "найди все места где используется ApiClient"

echo
echo "== 4. Сценарий 4: проверка инвариантов по CONVENTIONS.md =="
$PY main.py --goal "проверь соответствие кода правилам из CONVENTIONS.md"

echo
echo "== 5. Сценарий 2: обновление docs/api.md по коду (--dry-run) =="
echo "-- файл НЕ трогаем, показываем только предполагаемый diff --"
$PY main.py --goal "приведи docs/api.md в соответствие с кодом api_client.py" --dry-run

echo
echo "== 6. Сценарий 3: генерация project/README.md (реальная запись) =="
# README лежит в репозитории. Без удаления агент сразу скажет «изменений нет»,
# и факт записи на диск не будет виден. Удаляем → создаём заново: демо честное,
# а результат прежний — генерация детерминирована (тот же байт-в-байт файл).
rm -f project/README.md
$PY main.py --goal "сгенерируй README.md для проекта" --out report-readme.md

echo
echo "-- повторный запуск: тот же файл, записи не будет (идемпотентность) --"
$PY main.py --goal "сгенерируй README.md для проекта" --quiet

echo
echo "-- факт создания файла --"
if [ -f project/README.md ]; then
  echo "project/README.md существует: $(wc -l < project/README.md) строк, $(wc -c < project/README.md) байт"
  echo "-- первые 12 строк --"
  head -12 project/README.md
else
  echo "ОШИБКА: project/README.md не создан"
  exit 1
fi

echo
echo "== Готово. Отчёт по сценарию 3 → report-readme.md =="
