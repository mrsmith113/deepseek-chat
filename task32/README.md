# task32 — Автоматизация ревью кода (AI code review PR)

День 32 курса БЛМ. Пайплайн, где ассистент анализирует новый Pull Request:
получает diff и изменённые файлы, использует RAG (документация + код) и выдаёт
текст ревью — **потенциальные баги · архитектурные проблемы · рекомендации**.

## Как это работает

```
PR ──▶ git diff BASE...HEAD ──▶ diff_parser ──▶ heuristics (стат.анализ)
                                     │                  │
                                     ▼                  ▼
                                RAG (doc+код)  ──▶  reviewer (LLM-каскад)
                                                        │
                                                        ▼
                                              review.md ──▶ комментарий в PR
```

- **diff_parser.py** — из unified diff достаёт изменённые файлы и добавленные строки.
- **heuristics.py** — офлайн-линтер: секреты, `eval/exec`, широкие `except`,
  мутабельные дефолты, `== None`, `print`, длинные строки, крупный diff.
- **search.py + chunking.py + indexer.py** — RAG (TF-IDF, косинус) над
  документацией **и кодом** проекта. Индекс в `index.json`, без внешней БД.
- **reviewer.py** — собирает всё вместе; генерация: DeepSeek API → Ollama →
  без LLM (эвристики + RAG). Ревью содержательное в любом случае.
- **review.py** — CLI-точка входа (её зовёт GitHub Action).
- **.github/workflows/ai-review.yml** — запуск на `pull_request`, постинг ревью
  комментарием.

## Запуск (офлайн, одной командой)

```bash
bash run.sh
```

Или вручную:

```bash
python3 indexer.py                                  # собрать RAG-индекс
python3 review.py --diff samples/sample_pr.diff     # ревью демо-PR
python3 review.py --base origin/master --out review.md   # ревью реального PR
python3 review.py --no-llm                          # только эвристики + RAG
```

## LLM (опционально)

- `DEEPSEEK_API_KEY` — включает генерацию через DeepSeek.
- Иначе пробуется Ollama (`OLLAMA_MODEL`, по умолч. `qwen3:14b`) на :11434.
- Нет ни того, ни другого — ревью соберут эвристики + RAG-контекст.

## Зависимости

Нет. Только стандартная библиотека Python 3.10+.
