# Деплой Task 18 на NL №1

## 1. Создать папку и venv

```bash
mkdir -p /opt/challenge-bot && cd /opt/challenge-bot
python3 -m venv venv
venv/bin/pip install aiogram apscheduler aiohttp beautifulsoup4 openai mcp uvicorn httpx python-dotenv
```

## 2. Скопировать файлы

```powershell
# С локальной машины (PowerShell)
scp task18/db.py task18/parser.py task18/digest.py task18/scheduler.py task18/bot.py task18/server.py task18/agent.py root@82.21.53.191:/opt/challenge-bot/
```

## 3. Создать .env

```bash
nano /opt/challenge-bot/.env
# Заполнить по .env.example
chmod 600 /opt/challenge-bot/.env
```

## 4. Тест бота вручную

```bash
cd /opt/challenge-bot
set -a && source .env && set +a
venv/bin/python bot.py
# Ctrl+C после проверки
```

## 5. Запустить как systemd-сервис

```bash
cp /opt/challenge-bot/challenge-bot.service /etc/systemd/system/
cp /opt/challenge-bot/challenge-mcp.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now challenge-bot
systemctl enable --now challenge-mcp
```

## 6. Nginx — добавить location /mcp-news

```bash
# Открыть конфиг (тот же что для /mcp из Task 17)
nano /etc/nginx/sites-available/api.notifikatai.ru
# Вставить содержимое nginx-mcp-news.conf внутрь server{} блока 443
nginx -t && systemctl reload nginx
```

## 7. Проверка

```bash
# Статус
systemctl status challenge-bot
systemctl status challenge-mcp

# Логи
journalctl -u challenge-bot -f
journalctl -u challenge-mcp -f

# Тест MCP без Nginx
curl -s -X POST http://127.0.0.1:8001/mcp-news \
  -H "Authorization: Bearer challenge-mcp-2026" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# Тест через Nginx
curl -s -X POST https://api1.notifikatai.ru/mcp-news \
  -H "Authorization: Bearer challenge-mcp-2026" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

## 8. Запуск агента локально (демо)

```powershell
cd C:\Users\stasyouko\Downloads\klod\test\task18
$env:DEEPSEEK_API_KEY = "sk-..."
$env:MCP_TOKEN = "challenge-mcp-2026"
$env:DEMO_MODE = "1"
python agent.py
```

## Получить свой Telegram chat_id

Напиши @userinfobot — он пришлёт твой ID.
