#!/usr/bin/env python3
"""
smoke_app.py — минимальное CRUD-приложение как мишень для UI-smoke.

Сценарий курса День 3: логин → создать сущность → проверить что появилась →
удалить. Приложение самодостаточно (in-memory, без БД, без LLM/Ollama) —
поэтому smoke детерминирован и проходит стабильно, без внешних сервисов.

Сущность = «Заявка ТН ВЭД» (товар → предполагаемый код). Тематика проекта,
но логика тривиальна нарочно: тестируем UI-flow, а не бизнес-LLM.

Запуск:  uvicorn smoke_app:app --port 8799
Логин:   admin / secret
"""
from __future__ import annotations

import secrets
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="ВЭД Заявки — smoke target")

USER, PASSWORD = "admin", "secret"
_sessions: set[str] = set()          # активные токены
_items: dict[int, dict] = {}         # id → {"good":..., "code":...}
_next_id = 1


def _reset():
    """Чистое состояние (дёргается smoke-раннером перед прогоном)."""
    global _next_id
    _sessions.clear()
    _items.clear()
    _next_id = 1


def _authed(request: Request) -> bool:
    return request.cookies.get("session") in _sessions


# ---------- страницы ----------

def _page(body: str) -> str:
    return f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>ВЭД Заявки</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px}}
 h1{{font-size:22px}} input,button{{font-size:15px;padding:8px}}
 .item{{display:flex;justify-content:space-between;align-items:center;
        border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin:8px 0}}
 .err{{color:#c00}} form.inline{{display:inline}}
 button{{cursor:pointer;border-radius:6px;border:1px solid #888;background:#f5f5f5}}
</style></head><body>{body}</body></html>"""


LOGIN_HTML = _page("""
<h1>Вход</h1>
<form method=post action="/login">
  <p><input name=username placeholder="Логин" data-testid="login-user"></p>
  <p><input name=password type=password placeholder="Пароль" data-testid="login-pass"></p>
  <button type=submit data-testid="login-submit">Войти</button>
</form>
{error}
""")


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if _authed(request):
        return RedirectResponse("/items", status_code=303)
    return HTMLResponse(LOGIN_HTML.replace("{error}", ""))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == USER and password == PASSWORD:
        token = secrets.token_hex(8)
        _sessions.add(token)
        resp = RedirectResponse("/items", status_code=303)
        resp.set_cookie("session", token, httponly=True)
        return resp
    body = LOGIN_HTML.replace(
        "{error}", '<p class="err" data-testid="login-error">Неверный логин или пароль</p>')
    return HTMLResponse(body, status_code=401)


@app.get("/items", response_class=HTMLResponse)
def items(request: Request):
    if not _authed(request):
        return RedirectResponse("/", status_code=303)
    rows = ""
    for iid, it in sorted(_items.items()):
        rows += f"""<div class="item" data-testid="item-{iid}">
          <span>#{iid} · {it['good']} → <b>{it['code']}</b></span>
          <form class=inline method=post action="/items/{iid}/delete">
            <button type=submit data-testid="del-{iid}">Удалить</button>
          </form></div>"""
    if not rows:
        rows = '<p data-testid="empty">Заявок нет</p>'
    body = f"""
      <h1>Заявки ТН ВЭД <span data-testid="count">({len(_items)})</span></h1>
      <form method=post action="/items">
        <input name=good placeholder="Товар" data-testid="good">
        <input name=code placeholder="Код ТН ВЭД" data-testid="code">
        <button type=submit data-testid="add">Добавить</button>
      </form>
      <div data-testid="list">{rows}</div>
      <p><a href="/logout" data-testid="logout">Выйти</a></p>"""
    return HTMLResponse(_page(body))


@app.post("/items")
def add_item(request: Request, good: str = Form(...), code: str = Form(...)):
    if not _authed(request):
        raise HTTPException(401)
    global _next_id
    _items[_next_id] = {"good": good.strip(), "code": code.strip()}
    _next_id += 1
    return RedirectResponse("/items", status_code=303)


@app.post("/items/{iid}/delete")
def delete_item(request: Request, iid: int):
    if not _authed(request):
        raise HTTPException(401)
    _items.pop(iid, None)
    return RedirectResponse("/items", status_code=303)


@app.get("/logout")
def logout(request: Request):
    _sessions.discard(request.cookies.get("session"))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp


# служебное для smoke-раннера
@app.post("/__reset__")
def reset():
    _reset()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8799)
