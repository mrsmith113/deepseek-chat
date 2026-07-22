# День 3 — Testing (два уровня)

Полный цикл тестирования проекта БЛМ: код-тесты на бизнес-логику + UI-smoke,
которые агент прогоняет сам через Playwright, с отчётами и скриншотами.

## Что внутри

```
day03-testing/
  conftest.py            подключает task35/ и task33/ в sys.path
  pytest.ini
  requirements.txt
  level1_code/           Level 1 — unit/integration на РЕАЛЬНЫЕ модули проекта
    test_router.py         task35/router.py   (маршрутизация ТН ВЭД)
    test_router_bug.py     ← вскрыл реальный баг (xfail + документ)
    test_chunking.py       task33/chunking.py (нарезка базы знаний)
    test_metrics.py        task35/metrics.py  (P50/P95, cost, success rate)
    test_tool_registry.py  task35/tool_registry.py (реестр+executor)
  level2_smoke/          Level 2 — UI smoke через Playwright
    smoke_app.py           мишень: CRUD «Заявки ТН ВЭД» (self-contained)
    scenarios.md           5 пользовательских сценариев текстом
    smoke_runner.py        сам протыкивает UI, скрин на каждый шаг
    screenshots/           png по шагам (перезаписываются)
    SMOKE_REPORT.md        отчёт: pass/fail + скрины + где сломалось
  flow/
    run_all.sh             оба уровня одной командой → REPORT.md
    POST_PR_FLOW.md        интеграция в flow + «задеплоил фичу → обнови smoke»
  REPORT.md              сводный отчёт последнего прогона
```

## Запуск

```bash
# один раз — окружение
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Level 1
.venv/bin/python -m pytest

# Level 2
.venv/bin/python level2_smoke/smoke_runner.py

# оба уровня + сводный отчёт (для PR-гейта)
bash flow/run_all.sh "$(date '+%F %T')"
```

## Результат последнего прогона
- Level 1: **38 passed, 1 xfailed** (xfail документирует найденный баг).
- Level 2: **5/5 сценариев, 17/17 шагов**, 17 скриншотов.

## Найденный баг (Level 1 сработал по назначению)
`task35/router.py:19` — regex `[\d\s]{9,12}` требует ≥11 символов, поэтому
голый 10-значный код `8525893000` (без пробелов) НЕ распознаётся и запрос
уходит в дорогой FULL_PIPELINE вместо быстрого CODE_LOOKUP.
Фикс: `{9,12}` → `{8,12}`. Подробности — `level1_code/test_router_bug.py`.
