"""Доступ к CRM поддержки (data/crm.json): пользователи и тикеты.

Одна ответственность: читать CRM и отдавать данные в удобном виде —
как объекты (dict) для логики и как человекочитаемый текст для LLM/MCP.
Никакого RAG и никаких LLM здесь нет: только данные.

Структура data/crm.json:
    {"users":   [{"id":"U-100", "name":..., "plan":..., "sso_enabled":...}],
     "tickets": [{"id":"T-1042","user_id":"U-100","subject":...,
                  "error_code":..., "messages":[{"author":..,"at":..,"text":..}]}]}
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
CRM_PATH = HERE / "data" / "crm.json"


class CRMError(Exception):
    """Базовая ошибка CRM: файла нет, формат битый, запись не найдена."""


class NotFound(CRMError):
    """Запрошенный пользователь или тикет отсутствует в CRM."""


# ------------------------------------------------------------- загрузка ------
def load_crm(path: Path | None = None) -> dict:
    """Читает CRM из JSON. Понятно ругается, если файла нет или он битый."""
    p = path or CRM_PATH
    if not p.exists():
        raise CRMError(f"CRM не найдена: {p}. Ожидается файл data/crm.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CRMError(f"CRM повреждена ({p.name}): {e}") from e
    if not isinstance(data, dict) or "users" not in data or "tickets" not in data:
        raise CRMError(f"CRM {p.name}: ожидались ключи 'users' и 'tickets'")
    return data


# ------------------------------------------------------------- выборки -------
def get_user(user_id: str, crm: dict | None = None) -> dict:
    """Пользователь по id (U-100). NotFound, если такого нет."""
    crm = crm or load_crm()
    for u in crm["users"]:
        if u.get("id") == user_id:
            return u
    known = ", ".join(u.get("id", "?") for u in crm["users"][:10])
    raise NotFound(f"Пользователь {user_id} не найден. Есть: {known}")


def get_ticket(ticket_id: str, crm: dict | None = None) -> dict:
    """Тикет по id (T-1042). NotFound, если такого нет."""
    crm = crm or load_crm()
    for t in crm["tickets"]:
        if t.get("id") == ticket_id:
            return t
    known = ", ".join(t.get("id", "?") for t in crm["tickets"][:10])
    raise NotFound(f"Тикет {ticket_id} не найден. Есть: {known}")


def user_tickets(user_id: str, crm: dict | None = None) -> list[dict]:
    """Все тикеты пользователя, свежие сверху. Пустой список — это не ошибка."""
    crm = crm or load_crm()
    get_user(user_id, crm)  # проверяем, что пользователь существует
    tks = [t for t in crm["tickets"] if t.get("user_id") == user_id]
    return sorted(tks, key=lambda t: t.get("created_at", ""), reverse=True)


def search_tickets(query: str, limit: int = 5, crm: dict | None = None) -> list[dict]:
    """Поиск подстрокой (регистронезависимо) по subject, error_code и переписке."""
    crm = crm or load_crm()
    q = (query or "").strip().lower()
    if not q:
        raise CRMError("Пустой поисковый запрос")

    hits: list[dict] = []
    for t in crm["tickets"]:
        haystack = " ".join([
            str(t.get("subject", "")),
            str(t.get("error_code", "")),
            str(t.get("product_area", "")),
            " ".join(m.get("text", "") for m in t.get("messages", [])),
        ]).lower()
        if q in haystack:
            hits.append(t)
    return hits[:limit]


# ------------------------------------------------------------- рендер --------
def _flag(value: object) -> str:
    """Булев флаг человеческим языком."""
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "—"


def format_user(u: dict) -> str:
    """Карточка пользователя в человекочитаемом виде."""
    lines = [
        f"Пользователь {u.get('id')}: {u.get('name')}",
        f"  Компания:  {u.get('company', '—')}",
        f"  Email:     {u.get('email', '—')}",
        f"  Тариф:     {u.get('plan', '—')}   Роль: {u.get('role', '—')}",
        f"  SSO:       {_flag(u.get('sso_enabled'))}"
        f"   Домен верифицирован: {_flag(u.get('domain_verified'))}"
        f"   2FA: {_flag(u.get('twofa_enabled'))}",
        f"  С нами с:  {u.get('created_at', '—')}",
    ]
    if u.get("notes"):
        lines.append(f"  Заметки:   {u['notes']}")
    return "\n".join(lines)


def format_ticket(t: dict) -> str:
    """Карточка тикета с перепиской."""
    lines = [
        f"Тикет {t.get('id')}: {t.get('subject')}",
        f"  Клиент:    {t.get('user_id')}",
        f"  Статус:    {t.get('status', '—')}   Приоритет: {t.get('priority', '—')}",
        f"  Область:   {t.get('product_area', '—')}"
        f"   Код ошибки: {t.get('error_code') or '—'}",
        f"  Создан:    {t.get('created_at', '—')}",
    ]
    msgs = t.get("messages") or []
    if msgs:
        lines.append("  Переписка:")
        for m in msgs:
            who = {"user": "клиент", "agent": "поддержка"}.get(
                m.get("author", ""), m.get("author", "?"))
            lines.append(f"    [{m.get('at', '—')}] {who}: {m.get('text', '')}")
    else:
        lines.append("  Переписка: пусто")
    return "\n".join(lines)


if __name__ == "__main__":
    crm = load_crm()
    print(f"CRM загружена: пользователей={len(crm['users'])}, "
          f"тикетов={len(crm['tickets'])}")
    t = crm["tickets"][0]
    print()
    print(format_ticket(t))
    print()
    print(format_user(get_user(t["user_id"], crm)))
    print()
    hits = search_tickets("авториз", limit=3, crm=crm)
    print(f"Поиск 'авториз': {len(hits)} тикетов → "
          f"{', '.join(h['id'] for h in hits) or '—'}")
