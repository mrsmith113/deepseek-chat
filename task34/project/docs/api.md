# API-справочник: ApiClient

Класс `ApiClient` из модуля `api_client` — основная точка входа в yuko-sdk.
Через него выполняются все обращения к API таможенного брокера.

## Быстрый старт

```python
from api_client import ApiClient

client = ApiClient("https://api.notifikat.ru", token="secret", retries=3)
data = client.fetch("/declarations/42")
```

## `__init__(self, base_url, token, retries=3)`

Создаёт экземпляр клиента.

Параметры:

- `base_url` — базовый адрес API. Завершающий слэш отбрасывается.
- `token` — токен авторизации, подставляется в заголовок `Authorization: Bearer`.
- `retries` — количество повторных попыток при сетевой ошибке. По умолчанию `3`.

## `fetch(self, path, params=None)`

Универсальный метод получения данных. Выполняет запрос по указанному пути
и возвращает разобранное тело ответа в виде словаря.

Параметры:

- `path` — путь относительно `base_url`.
- `params` — словарь query-параметров.

Возвращает `dict` с телом ответа.

## `get(self, path, params=None)`

Выполняет GET-запрос. Тонкая обёртка над `fetch()`.

Параметры:

- `path` — путь относительно `base_url`.
- `params` — словарь query-параметров.

Возвращает `dict`.

## `post(self, path, payload=None)`

Выполняет POST-запрос с телом `payload`, сериализованным в JSON.

Параметры:

- `path` — путь относительно `base_url`.
- `payload` — словарь с телом запроса.

Возвращает `dict` с телом ответа.

## `_request(self, method, path, body)`

Внутренний метод. Не предназначен для прямого вызова из клиентского кода.
Собирает URL, добавляет заголовки авторизации и выполняет запрос.
