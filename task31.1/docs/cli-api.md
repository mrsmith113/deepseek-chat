# API и команды

## CLI (cli.py)

Интерактивный чат. Env `DEEPSEEK_API_KEY` обязателен.

| Команда | Действие |
|---|---|
| `/mode free` | Без ограничений (по умолчанию) |
| `/mode strict` | Краткий формат + стоп-фраза `[КОНЕЦ]` |
| `/mode nano` | Ровно 10 слов |
| `/settings` | Показать текущие настройки |
| `/clear` | Очистить историю диалога |
| `/help` | Справка |
| `выход` / `exit` | Выйти |

## Ассистент разработчика (task32)

### assistant.py — команда /help

```bash
python3 assistant.py "как устроен RAG в проекте?"
python3 assistant.py            # интерактивный режим, команда /help
```

Пайплайн: вопрос → RAG-поиск по README+docs → сбор git-контекста через MCP-
инструменты → генерация ответа (DeepSeek если есть ключ, иначе extractive).

### MCP-инструменты (mcp_server.py)

Сервер Model Context Protocol, транспорт stdio. Инструменты:

| Инструмент | Вход | Выход |
|---|---|---|
| `git_branch` | — | текущая ветка репозитория |
| `git_files` | — | список файлов под контролем git |
| `git_diff` | `staged?: bool` | unified diff рабочего дерева |

### RAG-индекс (index.json)

Формат: массив объектов чанков.

```json
{
  "chunk_id": 0,
  "source": "README.md",
  "title": "deepseek-chat",
  "section": "Стек",
  "text": "LLM: DeepSeek API ..."
}
```

## Схема эмбеддингов

- Backend по умолчанию: **TF-IDF** (чистый stdlib, без зависимостей).
- Опционально: **sentence-transformers** (dense-векторы), если установлен.
- Метрика близости: косинус.
