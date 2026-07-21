"""notify.py — сводка тикета поддержки и её отправка на webhook.

Роль в пайплайне:
  1. Загружаем CRM и достаём тикет + его пользователя (модуль crm_tools).
  2. Собираем краткую текстовую сводку по тикету.
  3. Отправляем JSON POST на NOTIFY_WEBHOOK; если он пуст — печатаем в stdout.

Ключевая идея: сводка формируется всегда, доставка — опциональна. Нет
webhook или нет сети — не роняем процесс, а печатаем результат локально.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# crm_tools лежит в соседней папке task33 — добавляем её в путь импорта.
_CRM_DIR = Path(__file__).resolve().parent.parent / "task33"
if str(_CRM_DIR) not in sys.path:
    sys.path.insert(0, str(_CRM_DIR))

import crm_tools  # noqa: E402  (импорт после правки sys.path — намеренно)

# ---- Константы -------------------------------------------------------------
WEBHOOK = os.getenv("NOTIFY_WEBHOOK", "")   # пусто → печатаем сводку в stdout
TIMEOUT = 10                                # сек на HTTP-запрос


# ---- Публичный API ---------------------------------------------------------
def build_summary(ticket_id: str, crm: dict | None = None) -> dict:
    """Собирает краткую сводку по тикету в виде структурированного dict.

    Тянет тикет и его пользователя из CRM, вынимает ключевые поля:
    статус тикета, тариф и роль пользователя, код ошибки и последнее
    сообщение переписки.
    """
    crm = crm or crm_tools.load_crm()
    ticket = crm_tools.get_ticket(ticket_id, crm)
    user = crm_tools.get_user(ticket.get("user_id", ""), crm)

    return {
        "ticket_id": ticket.get("id", ticket_id),
        "status": ticket.get("status", "—"),
        "plan": user.get("plan", "—"),
        "role": user.get("role", "—"),
        "error_code": ticket.get("error_code") or "—",
        "last_message": _last_message(ticket),
    }


def render_summary(summary: dict) -> str:
    """Человекочитаемый текст сводки для stdout/лога."""
    return "\n".join([
        f"Тикет:          {summary['ticket_id']}",
        f"Статус:         {summary['status']}",
        f"Тариф / роль:   {summary['plan']} / {summary['role']}",
        f"Код ошибки:     {summary['error_code']}",
        f"Последнее сообщение: {summary['last_message']}",
    ])


def notify(ticket_id: str, crm: dict | None = None) -> dict:
    """Формирует сводку и доставляет её: на webhook либо в stdout.

    Возвращает саму сводку, чтобы вызывающий код мог её переиспользовать.
    """
    summary = build_summary(ticket_id, crm)

    if not WEBHOOK:
        # Фолбэк: нет адреса доставки — печатаем сводку локально.
        print(render_summary(summary))
        return summary

    _post_json(WEBHOOK, summary)
    return summary


# ---- Приватные хелперы -----------------------------------------------------
def _last_message(ticket: dict) -> str:
    """Текст последнего сообщения переписки (или прочерк, если её нет)."""
    messages = ticket.get("messages") or []
    if not messages:
        return "—"
    last = messages[-1]
    author = last.get("author", "?")
    text = last.get("text", "")
    return f"[{author}] {text}"


def _post_json(url: str, payload: dict) -> None:
    """POST JSON на webhook. Ошибку сети/HTTP ловим и печатаем сводку локально."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            print(f"Отправлено на webhook: HTTP {resp.status}")
    except (urllib.error.URLError, TimeoutError) as e:
        # Сеть недоступна — не роняем процесс, показываем сводку в stdout.
        print(f"Webhook недоступен ({e}). Сводка ниже:")
        print(render_summary(payload))


# ---- CLI-точка входа -------------------------------------------------------
def main() -> None:
    """Запуск: python notify.py T-1042"""
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not ticket_id:
        print("Использование: python notify.py <ticket_id>   (например T-1042)")
        sys.exit(1)

    try:
        notify(ticket_id)
    except crm_tools.CRMError as e:
        print(f"Ошибка CRM: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
