"""CLI ассистента поддержки — точка входа для человека и для демо.

Примеры:
    python3 support.py --ticket T-1042 --question "Почему не работает авторизация?"
    python3 support.py --user U-100 --question "Как выгрузить документы?"
    python3 support.py --question "Что такое нотификация ФСБ?"   # чистый RAG
    python3 support.py --demo                                    # 3 кейса подряд
    python3 support.py --ticket T-1042 --question "..." --out answer.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from assistant import answer

# показательные кейсы: с тикетом, по клиенту без тикета, вообще без контекста
DEMO_CASES = [
    {"question": "Почему не работает авторизация?", "ticket": "T-1042",
     "title": "Тикет T-1042 — контекст клиента решает"},
    {"question": "Как получить API-ключ для интеграции с 1С?", "user": "U-104",
     "title": "Клиент U-104 без тикета — упирается в лимит тарифа Free"},
    {"question": "Как выгрузить документы из кабинета?",
     "title": "Без контекста — чистый RAG по базе знаний"},
]


def run_demo() -> None:
    for i, case in enumerate(DEMO_CASES, 1):
        print("=" * 72)
        print(f"ДЕМО {i}/{len(DEMO_CASES)}: {case['title']}")
        print("=" * 72)
        try:
            print(answer(case["question"], ticket_id=case.get("ticket"),
                         user_id=case.get("user")))
        except Exception as e:
            print(f"[кейс пропущен: {e}]")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ассистент поддержки пользователей (task33)")
    ap.add_argument("--question", "-q", help="вопрос клиента")
    ap.add_argument("--ticket", help="id тикета, например T-1042")
    ap.add_argument("--user", help="id клиента, например U-100")
    ap.add_argument("--out", help="сохранить ответ в markdown-файл")
    ap.add_argument("--no-llm", action="store_true",
                    help="без LLM — только правила и RAG")
    ap.add_argument("--demo", action="store_true",
                    help="прогнать 3 показательных кейса")
    args = ap.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.question:
        ap.error("нужен --question (или --demo)")

    try:
        text = answer(args.question, ticket_id=args.ticket,
                      user_id=args.user, use_llm=not args.no_llm)
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Ответ записан → {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
