#!/bin/bash
# Демо AI code review (task32) — офлайн, одной командой.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo "== 1. Строю RAG-индекс (документация + код) =="
$PY indexer.py

echo
echo "== 2. Ревью демо-PR (samples/sample_pr.diff) =="
$PY review.py --diff samples/sample_pr.diff --out review.md
echo "Готово. Результат:"
echo
cat review.md
