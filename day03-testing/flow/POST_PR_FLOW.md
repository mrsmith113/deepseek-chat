# Встраивание тестов в flow разработки

Оба уровня — одной командой, после каждого PR / перед мержем.

## 1. Гейт на PR

```bash
bash flow/run_all.sh "$(date '+%F %T')"
```

- Level 1 (pytest) + Level 2 (Playwright smoke) прогоняются подряд.
- Exit-код: `0` только если оба зелёные → CI-гейт блокирует мерж при падении.
- Сводка → `REPORT.md`, детали смоука + скрины → `level2_smoke/`.

Пример GitHub Actions (`.github/workflows/day03-tests.yml`):
```yaml
name: day03-tests
on: { pull_request: { paths: ["GIT/day03-testing/**", "GIT/task33/**", "GIT/task35/**"] } }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pytest fastapi uvicorn python-multipart playwright && playwright install chromium
      - run: cd GIT/day03-testing && bash flow/run_all.sh "$(date '+%F %T')"
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: smoke-screenshots, path: GIT/day03-testing/level2_smoke/screenshots/ }
```

## 2. Сценарий «задеплоил новую фичу → обнови smoke и прогони всё»

Регламент для агента (skill-шаги):

1. **Что изменилось.** Прочитать diff фичи: новые страницы/поля/кнопки, новый endpoint.
2. **Level 1.** Есть новая бизнес-логика (функция/модуль)? → дописать `level1_code/test_<модуль>.py`
   на happy-path + граничные случаи. Прогнать `pytest` — должно быть зелено.
3. **Level 2.** Появился новый UI-элемент/поток? →
   - добавить сценарий в `level2_smoke/scenarios.md` (текстом: шаги + проверка);
   - добавить `run_scenario(...)` в `smoke_runner.py` c `data-testid` новых элементов;
   - если фича = новая сущность → расширить CRUD-поток (create/verify/delete).
4. **Прогнать всё заново.** `bash flow/run_all.sh "$(date '+%F %T')"` → новый `REPORT.md` + свежие скрины.
5. **Если упало.** Агент указывает: уровень, сценарий/тест, шаг, ожидание vs факт,
   скриншот момента падения — и гипотезу «где чинить» (файл: точка).

Команда-триггер (устно агенту):
> «Я задеплоил фичу X — обнови smoke-сценарии и прогони весь тест-пакет заново.»

Агент выполняет шаги 1–5 и возвращает сводный отчёт.
