# yuko-sdk

Учебная библиотека для работы с API таможенного брокера Юко: нотификации ФСБ, декларации, отчёты.

> Файл сгенерирован автоматически ассистентом (`agent.py`, сценарий «генерация README») по коду проекта.

## Возможности

- **`api_client.py`** — HTTP-клиент для API таможенного брокера Юко.
- **`handlers.py`** — Обработчики бизнес-сценариев: нотификации и декларации.
- **`reports.py`** — Построение и выгрузка отчётов по декларациям.
- **`utils.py`** — Вспомогательные функции общего назначения.

## Структура

```
CONVENTIONS.md
api_client.py
docs/api.md
docs/architecture.md
handlers.py
reports.py
utils.py
```

## Публичный API

### `api_client.py`

Константы: `DEFAULT_TIMEOUT = 30`, `DEFAULT_RETRY_COUNT = 3`

- `class ApiClient` — Клиент для работы с API yuko-sdk.
  - `__init__(base_url, token, timeout=30)` — Создаёт клиент.
  - `get(path, params=None)` — Выполняет GET-запрос.
  - `post(path, payload=None)`
  - `close()`
  - `retry_count` *(property)* — Число повторных попыток при сбое запроса.

### `handlers.py`

- `handle_notification(client, decl_id)` — Забирает статус нотификации ФСБ по идентификатору декларации.
- `handle_declaration(client, data)` — Отправляет декларацию на регистрацию.
- `make_default_client(token)` — Собирает клиент с настройками по умолчанию.

### `reports.py`

- `build_report(cfg)` — Строит отчёт по конфигурации.
- `export_csv(rows, path)`

### `utils.py`

- `chunked(seq, n)` — Разбивает последовательность на куски по n элементов.
- `slugify(text)` — Превращает произвольный текст в slug для URL.

## Установка

Внешних зависимостей нет — нужен только Python 3.10+.

```bash
git clone <repo>
cd yuko-sdk
```

## Использование

```python
from handlers import make_default_client, handle_notification

client = make_default_client(token="secret")
status = handle_notification(client, decl_id="42")
```

## Соглашения

Правила кода — в [CONVENTIONS.md](CONVENTIONS.md). Документация — в [docs/](docs/).
