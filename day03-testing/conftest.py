"""Общий conftest: подключаем модули реальных тасков в sys.path.

Level 1 тестирует бизнес-логику ИЗ проекта (не копии):
  task35/router.py, task35/metrics.py, task35/tool_registry.py
  task33/chunking.py
"""
import sys
from pathlib import Path

GIT_ROOT = Path(__file__).resolve().parent.parent  # .../GIT
for sub in ("task35", "task33"):
    p = GIT_ROOT / sub
    if p.exists():
        sys.path.insert(0, str(p))
