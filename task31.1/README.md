# deepseek-chat — учебный проект курса БЛМ

Репозиторий: https://github.com/mrsmith113/deepseek-chat

Это рабочий репозиторий курса «Большие Языковые Модели» (Alex Gladkov). Каждое
домашнее задание — отдельная папка `taskN/` в корне. Внутри — код задания,
пояснение (`EXPLANATION.md`) и сценарий видео (`VIDEO_SCENARIO.md`).

## Что делает проект

Проект развивается от простого CLI-чата с DeepSeek API до полноценного
RAG-стека с локальной LLM, MCP-серверами и агентами. Ветка разработки — `master`.

## Стек

- **LLM:** DeepSeek API (облако) + Ollama/Qwen3 14B (локально).
- **Эмбеддинги:** GigaEmbeddings (ai-sage, 2048 dim).
- **Векторная БД:** Qdrant (HTTP :6333), коллекция `youtube_rag`.
- **RAG-сервер:** FastAPI :8000 + MCP :8002.
- **Данные:** 351 YouTube-транскрипт компании Юко.
- **Python:** venv `~/rag-env/` (RAG-стек), `~/torch-env/` (torch).

## Как устроен репозиторий

- Корень — ранние таски одним файлом: `cli.py`, `bot.py`, `task3.py`…`task11.py`.
- `taskN/` — поздние таски папкой (RAG, MCP, агенты).
- Каждый таск самодостаточен: запускается одной командой.

## Ключевые команды CLI (cli.py)

- `/mode free|strict|nano` — режим ответа модели.
- `/settings` — показать настройки.
- `/clear` — очистить историю диалога.
- `/help` — справка.
- `выход` / `exit` — выйти.

## Как запустить чат

```bash
export DEEPSEEK_API_KEY=sk-...
python3 cli.py
```

## Git-workflow

```bash
cd GIT
git add taskN/
git commit -m "taskN: описание"
git push origin master
```

Подробнее — в `docs/architecture.md`, `docs/tasks.md`, `docs/cli-api.md`.
