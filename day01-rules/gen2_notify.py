"""Сервис уведомлений: краткая сводка тикета → webhook.

Роль в пайплайне:
  1. По ticket_id читаем тикет и связанного пользователя из CRM (crm_tools).
  2. Собираем компактную текстовую сводку: id, статус, тариф и роль клиента,
     код ошибки, последнее сообщение переписки.
  3. Шлём сводку POST-запросом (JSON) на URL из NOTIFY_WEBHOOK.
  4. Если webhook не задан или сеть недоступна — печатаем сводку в stdout.

Ключевая идея: уведомление обязано доехать хоть куда-то. Webhook — усилитель,
а не единственная опора: при пустом URL или сетевой ошибке деградируем на stdout,
а не роняем процесс (принцип каскада с деградацией, §5.1).
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error

# сначала stdlib, потом внутрипроектные импорты
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "task33"))
import crm_tools

# ---- Константы -------------------------------------------------------------
WEBHOOK = os.getenv("NOTIFY_WEBHOOK", "")   # пусто → печатаем сводку в stdout
TIMEOUT = 10          # сек на HTTP-запрос, чтобы не висеть на мёртвом webhook
_DASH = "—"           # заглушка для отсутствующего значения в сводке


# ---- Публичный API ---------------------------------------------------------
def build_summary(ticket_id: str, crm: dict | None = None) -> str:
    """Собирает текстовую сводку тикета для уведомления.

    Тянет тикет и его пользователя из CRM, вытаскивает статус, тариф и роль
    клиента, код ошибки и последнее сообщение переписки.
    """
    crm = crm or crm_tools.load_crm()
    ticket = crm_tools.get_ticket(ticket_id, crm)
    user = _safe_user(ticket.get("user_id", ""), crm)

    plan = user.get("plan", _DASH) if user else _DASH
    role = user.get("role", _DASH) if user else _DASH
    lines = [
        f"Тикет {ticket.get('id', _DASH)}: {ticket.get('subject', _DASH)}",
        f"  Статус:     {ticket.get('status', _DASH)}",
        f"  Клиент:     тариф {plan}, роль {role}",
        f"  Код ошибки: {ticket.get('error_code') or _DASH}",
        f"  Последнее:  {_last_message(ticket)}",
    ]
    return "\n".join(lines)


def notify(ticket_id: str, crm: dict | None = None) -> str:
    """Формирует сводку и доставляет её: webhook при наличии URL, иначе stdout.

    Возвращает канал доставки ('webhook' или 'stdout') для наглядности в CLI.
    """
    summary = build_summary(ticket_id, crm)
    if not WEBHOOK:
        print(summary)
        return "stdout"
    if _post_json(WEBHOOK, {"ticket_id": ticket_id, "summary": summary}):
        return "webhook"
    # сеть/webhook подвели — не теряем уведомление, деградируем на stdout
    print(summary)
    return "stdout"


# ---- Приватные хелперы -----------------------------------------------------
def _safe_user(user_id: str, crm: dict) -> dict | None:
    """Пользователь по id или None, если запись отсутствует в CRM."""
    if not user_id:
        return None
    try:
        return crm_tools.get_user(user_id, crm)
    except crm_tools.NotFound:
        return None


def _last_message(ticket: dict) -> str:
    """Текст последнего сообщения переписки тикета."""
    msgs = ticket.get("messages") or []
    if not msgs:
        return "(переписки нет)"
    return str(msgs[-1].get("text", "")).strip() or _DASH


def _post_json(url: str, payload: dict) -> bool:
    """POST JSON на url. True при успехе, False при сетевой ошибке."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


# ---- CLI-точка входа -------------------------------------------------------
def main() -> None:
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not ticket_id:
        print("Использование: python notify.py <TICKET_ID>   (напр. T-1042)")
        raise SystemExit(2)
    channel = notify(ticket_id)   # print внутри — вывод результата (§7.2)
    if channel == "webhook":
        print(f"Сводка по {ticket_id} отправлена на webhook.")


if __name__ == "__main__":
    main()
