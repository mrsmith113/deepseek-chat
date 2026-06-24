# Контекст: Таск 17 — MCP-сервер поверх CouchDB (remote deploy)

## Что сделано

MCP-сервер поверх CouchDB REST API задеплоен на NL №1.
Агент подключается через Streamable HTTP с Bearer-токеном.

**Папка:** `task17/`
**Файлы:** `server.py`, `agent.py`, `mcp-couchdb.service`, `nginx-mcp.conf`, `.env.example`

---

## Ключевые отличия от Таска 16

| Таск 16 | Таск 17 |
|---------|---------|
| `tools/list` — только обнаружение | `tools/call` — реальный вызов |
| stdio транспорт (локальный subprocess) | Streamable HTTP (remote, задеплоен) |
| Без LLM | DeepSeek через function calling |
| Mock-инструменты | Реальный CouchDB API |

---

## Инструменты MCP-сервера

```
list_databases()                     →  GET  /_all_dbs
get_document(database, document_id)  →  GET  /{db}/{id}
save_document(database, id, data)    →  PUT  /{db}/{id}
```

---

## Архитектура деплоя

```
Клиент (локально)
    │
    │  HTTPS  Authorization: Bearer <token>
    ▼
api.notifikatai.ru/mcp   (Nginx + SSL, NL №1)
    │
    │  proxy_pass  http://127.0.0.1:8000/mcp
    ▼
MCP-сервер (uvicorn, порт 8000, NL №1)
    │  BearerAuthMiddleware проверяет токен
    │  FastMCP Streamable HTTP транспорт
    ▼
CouchDB REST API (http://91.229.11.116:5984)
```

---

## Деплой на NL №1 — пошагово

```bash
# 1. Копируем файлы на сервер
scp task17/server.py root@82.21.53.191:/opt/mcp-couchdb/
scp task17/mcp-couchdb.service root@82.21.53.191:/etc/systemd/system/

# 2. На сервере — создаём окружение
ssh root@82.21.53.191

cd /opt/mcp-couchdb
python3 -m venv venv
venv/bin/pip install mcp httpx uvicorn

# 3. Создаём .env
cat > /opt/mcp-couchdb/.env << 'EOF'
COUCHDB_URL=http://91.229.11.116:5984
COUCHDB_USER=admin
COUCHDB_PASS=ВАШ_ПАРОЛЬ
MCP_TOKEN=ВАШ_СЕКРЕТНЫЙ_ТОКЕН
MCP_HOST=127.0.0.1
MCP_PORT=8000
EOF

# 4. Запускаем через systemd
systemctl daemon-reload
systemctl enable mcp-couchdb
systemctl start mcp-couchdb
systemctl status mcp-couchdb

# 5. Nginx — добавляем location /mcp в существующий конфиг
nano /etc/nginx/sites-available/api.notifikatai.ru
# (вставить содержимое nginx-mcp.conf внутрь server {} блока 443)

nginx -t && systemctl reload nginx
```

---

## Запуск агента локально

```powershell
# Зависимости
pip install mcp httpx openai

# Переменные
$env:DEEPSEEK_API_KEY = "sk-..."
$env:MCP_TOKEN        = "ваш_токен"
# MCP_URL по умолчанию: https://api.notifikatai.ru/mcp

# Демо-режим (для видео)
$env:DEMO_MODE = "1"
python agent.py

# Интерактивный режим
python agent.py
```

---

## Полный цикл вызова

```
User                Agent (LLM)            Nginx+MCP Server        CouchDB
 │                      │                        │                     │
 │── "Какие БД есть?" ──►│                        │                     │
 │                      │── POST /mcp ────────────►│                     │
 │                      │   tools/list             │                     │
 │                      │◄─ [list_databases...] ───│                     │
 │                      │                        │                     │
 │         (DeepSeek решает: нужен list_databases)│                     │
 │                      │                        │                     │
 │                      │── POST /mcp ────────────►│                     │
 │                      │   tools/call             │                     │
 │                      │   list_databases({})     │── GET /_all_dbs ───►│
 │                      │                        │◄─ ["hornest",...] ───│
 │                      │◄─ результат ─────────────│                     │
 │                      │                        │                     │
 │◄─ "В CouchDB 2 БД: hornest, logs" ────────────│                     │
```

---

## Ключевые строки кода

```python
# server.py — Streamable HTTP вместо stdio
app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)
uvicorn.run(app, host="127.0.0.1", port=8000)

# agent.py — remote client вместо subprocess
from mcp.client.streamable_http import streamable_http_client
headers = {"Authorization": f"Bearer {MCP_TOKEN}"}
async with streamable_http_client(MCP_URL, headers=headers) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tool_result = await session.call_tool(tool_name, tool_args)
```

---

## Связь с роудмапом платформы

Этот деплой — прообраз `mcp-servers/qdrant-mcp/`, `mcp-servers/files-mcp/` из Фазы 3.

Паттерн переиспользуется для всех будущих MCP-серверов платформы:
- Один systemd-сервис на сервер
- Один location /mcp-{name} в Nginx
- Один MCP_TOKEN на сервис
- Все агенты подключаются через HTTP

---

## GitHub

```
https://github.com/mrsmith113/deepseek-chat
ветка: master
папка: task17/
```
