# Task 19 — Деплой MCP Pipeline сервера

## Что делаем

Новый MCP-сервер на порту 8002 с тремя инструментами:
- `search_posts` — читает SQLite базу Task18
- `summarize_with_humor` — DeepSeek с чёрным юмором
- `save_to_file` — сохраняет результат на диск

## 1. Сервер NL №1

```bash
mkdir -p /opt/mcp-pipeline && cd /opt/mcp-pipeline

# Venv (--without-pip если зависает)
python3 -m venv --without-pip venv
curl bootstrap.pypa.io/get-pip.py | venv/bin/python
venv/bin/pip install mcp httpx uvicorn python-dotenv starlette

# Копируем файлы
scp task19/server.py root@82.21.53.191:/opt/mcp-pipeline/

# .env
nano /opt/mcp-pipeline/.env   # заполнить по .env.example
chmod 600 /opt/mcp-pipeline/.env

# Тест вручную
set -a && source .env && set +a
venv/bin/python server.py
# Ctrl+C

# Systemd
cp task19/mcp-pipeline.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mcp-pipeline
systemctl status mcp-pipeline
```

## 2. Nginx

```bash
# Добавить location из nginx-mcp-pipeline.conf в существующий server{} блок
nano /etc/nginx/sites-available/api1.notifikatai.ru
# вставить содержимое nginx-mcp-pipeline.conf

nginx -t && systemctl reload nginx
```

## 3. Бот Task18

```bash
# Добавить в /opt/challenge-bot/.env:
MCP_PIPELINE_URL=https://api1.notifikatai.ru/mcp-pipeline
MCP_PIPELINE_TOKEN=pipeline-mcp-2026

# Копируем обновлённые файлы
scp task18/bot.py root@82.21.53.191:/opt/challenge-bot/
scp task18/db.py  root@82.21.53.191:/opt/challenge-bot/

systemctl restart challenge-bot
```

## 4. Диагностика

```bash
# Логи pipeline сервера
journalctl -u mcp-pipeline -f

# Тест без Nginx
curl -s -X POST http://127.0.0.1:8002/mcp \
  -H "Authorization: Bearer pipeline-mcp-2026" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# Тест через Nginx
curl -o /dev/null -w "%{http_code}" \
  https://api1.notifikatai.ru/mcp-pipeline
# Без токена должен вернуть 401
```

## 5. Использование в боте

```
/pipeline                      — посты @alexgladkovblog за 24ч (по умолчанию)
/pipeline alexgladkovblog      — то же самое явно
/pipeline sergeinotevskii 48   — посты Нотевского за 48ч
/pipeline aostrikov_ai_agents  — посты Острикова
```

## Потоки данных

```
/pipeline alexgladkovblog
    ↓
bot.py → MCP Client (Streamable HTTP + Bearer)
    ↓
api1.notifikatai.ru/mcp-pipeline → server.py (порт 8002)
    │
    ├─ search_posts("alexgladkovblog", 24)
    │       └─ SELECT FROM /opt/challenge-bot/challenge.db
    │              → "Posts from @alexgladkovblog (last 24h): 3 found..."
    │
    ├─ summarize_with_humor(posts_text, "alexgladkovblog")
    │       └─ POST https://api.notifikatai.ru/api/deepseek
    │              → "Вчера Гладков вещал о том, что AGI..."
    │
    └─ save_to_file(summary, "alexgladkovblog")
            └─ /opt/mcp-pipeline/results/20260625_120000_alexgladkovblog.txt
                   → "Saved: /opt/mcp-pipeline/results/..."
    ↓
bot.py → Telegram: "✅ Пайплайн завершён\n\nВчера Гладков вещал о том..."
```
