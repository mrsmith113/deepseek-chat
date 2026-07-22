#!/usr/bin/env bash
# run_all.sh — единый прогон обоих уровней тестирования + сводный отчёт.
# Встраивается в flow разработки: вызывать после PR / перед мержем.
#
#   bash flow/run_all.sh
#
# Выход: 0 если всё зелёное, иначе != 0. Сводный отчёт → REPORT.md.
set -u
cd "$(dirname "$0")/.." || exit 2
PY=.venv/bin/python
STAMP="$1"                      # передаётся снаружи (в скрипте нет Date.now)
[ -z "${STAMP:-}" ] && STAMP="(время не передано)"

echo "== Level 1: код-тесты =="
$PY -m pytest -o addopts="-ra" > /tmp/day03_l1.txt 2>&1
L1=$?
tail -3 /tmp/day03_l1.txt

echo ""
echo "== Level 2: UI smoke (Playwright) =="
$PY level2_smoke/smoke_runner.py > /tmp/day03_l2.txt 2>&1
L2=$?
tail -6 /tmp/day03_l2.txt

L1_LINE=$(grep -aE "[0-9]+ (passed|failed)" /tmp/day03_l1.txt | tail -1)
L2_LINE=$(grep -E "Сценарии:" /tmp/day03_l2.txt | tail -1)

{
  echo "# Сводный отчёт тестирования — День 3"
  echo ""
  echo "Прогон: $STAMP"
  echo ""
  echo "## Level 1 — код-тесты (pytest)"
  echo '```'
  echo "$L1_LINE"
  echo '```'
  echo "Статус: $([ $L1 -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')  · подробности: \`level1_code/\`"
  echo ""
  echo "## Level 2 — UI smoke (Playwright)"
  echo '```'
  echo "$L2_LINE"
  echo '```'
  echo "Статус: $([ $L2 -eq 0 ] && echo '✅ PASS' || echo '❌ FAIL')  · отчёт: \`level2_smoke/SMOKE_REPORT.md\` · скрины: \`level2_smoke/screenshots/\`"
  echo ""
  echo "## Итог"
  echo "$([ $L1 -eq 0 ] && [ $L2 -eq 0 ] && echo '✅ Оба уровня зелёные — можно мержить.' || echo '❌ Есть падения — смотри отчёты уровней, мерж заблокирован.')"
} > REPORT.md

echo ""
echo "Сводный отчёт: REPORT.md"
[ $L1 -eq 0 ] && [ $L2 -eq 0 ]
