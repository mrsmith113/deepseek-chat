"""
Task 17 — MCP-сервер поверх CouchDB REST API
Транспорт: Streamable HTTP (remote deployment)
SDK: mcp 1.28.0
Деплой: NL №1 (82.21.53.191), systemd
"""

import os
import json
import httpx
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# ── Настройки ──────────────────────────────────────────────────────
COUCHDB_URL  = os.getenv("COUCHDB_URL",  "http://91.229.11.116:5984")
COUCHDB_USER = os.getenv("COUCHDB_USER", "admin")
COUCHDB_PASS = os.getenv("COUCHDB_PASS", "password")
MCP_TOKEN    = os.getenv("MCP_TOKEN",    "change-me")
MCP_HOST     = os.getenv("MCP_HOST",     "0.0.0.0")
MCP_PORT     = int(os.getenv("MCP_PORT", "8000"))

AUTH = (COUCHDB_USER, COUCHDB_PASS)

# ── Bearer auth middleware ─────────────────────────────────────────
class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != MCP_TOKEN:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)

# ── MCP-сервер ─────────────────────────────────────────────────────
mcp = FastMCP("CouchDB Tools")


@mcp.tool()
def list_databases() -> str:
    """
    Возвращает список всех баз данных в CouchDB.
    Используй когда нужно узнать какие БД существуют.
    """
    try:
        resp = httpx.get(f"{COUCHDB_URL}/_all_dbs", auth=AUTH, timeout=10)
        resp.raise_for_status()
        dbs = resp.json()
        user_dbs   = [db for db in dbs if not db.startswith("_")]
        system_dbs = [db for db in dbs if db.startswith("_")]
        result  = f"Баз данных всего: {len(dbs)}\n"
        result += f"Пользовательские ({len(user_dbs)}): {', '.join(user_dbs) if user_dbs else 'нет'}\n"
        result += f"Системные ({len(system_dbs)}): {', '.join(system_dbs)}"
        return result
    except httpx.ConnectError:
        return "Ошибка: не удалось подключиться к CouchDB."
    except httpx.HTTPStatusError as e:
        return f"Ошибка HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Неожиданная ошибка: {e}"


@mcp.tool()
def get_document(database: str, document_id: str) -> str:
    """
    Получает документ из CouchDB по его ID.

    Args:
        database: имя базы данных (например 'hornest')
        document_id: ID документа (например 'user_001')
    """
    try:
        resp = httpx.get(
            f"{COUCHDB_URL}/{database}/{document_id}",
            auth=AUTH, timeout=10,
        )
        if resp.status_code == 404:
            return f"Документ '{document_id}' не найден в базе '{database}'."
        resp.raise_for_status()
        doc = resp.json()
        return f"Документ '{document_id}' из базы '{database}':\n" + \
               json.dumps(doc, ensure_ascii=False, indent=2)
    except httpx.ConnectError:
        return "Ошибка: не удалось подключиться к CouchDB."
    except httpx.HTTPStatusError as e:
        return f"Ошибка HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Неожиданная ошибка: {e}"


@mcp.tool()
def save_document(database: str, document_id: str, data: str) -> str:
    """
    Сохраняет или обновляет документ в CouchDB.

    Args:
        database: имя базы данных (например 'hornest')
        document_id: ID документа (например 'task17')
        data: содержимое документа в формате JSON-строки
              (например '{"name": "Hornest", "status": "done"}')
    """
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as e:
        return f"Ошибка: data должна быть валидным JSON. {e}"

    try:
        existing = httpx.get(
            f"{COUCHDB_URL}/{database}/{document_id}",
            auth=AUTH, timeout=10,
        )
        if existing.status_code == 200:
            current_rev = existing.json().get("_rev")
            if "_rev" not in payload and current_rev:
                payload["_rev"] = current_rev

        resp = httpx.put(
            f"{COUCHDB_URL}/{database}/{document_id}",
            auth=AUTH, json=payload, timeout=10,
        )
        resp.raise_for_status()
        action = "обновлён" if existing.status_code == 200 else "создан"
        rev = resp.json().get("rev", "неизвестно")
        return f"Документ '{document_id}' успешно {action} в базе '{database}'.\nНовая версия: {rev}"
    except httpx.ConnectError:
        return "Ошибка: не удалось подключиться к CouchDB."
    except httpx.HTTPStatusError as e:
        return f"Ошибка HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Неожиданная ошибка: {e}"


# ── Точка входа ────────────────────────────────────────────────────
app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)

if __name__ == "__main__":
    print(f"🚀 MCP CouchDB сервер запущен на {MCP_HOST}:{MCP_PORT}")
    print(f"📡 Эндпоинт: http://{MCP_HOST}:{MCP_PORT}/mcp")
    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)
