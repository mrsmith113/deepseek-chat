"""CLI файлового ассистента — точка входа для человека и для демо.

Примеры:
    python3 main.py --goal "найди все места где используется ApiClient"
    python3 main.py --goal "приведи docs/api.md в соответствие с кодом api_client.py" --dry-run
    python3 main.py --goal "сгенерируй README.md для проекта" --out report.md
    python3 main.py                       # список демо-целей

Задача ставится ЦЕЛЬЮ, а не командой: какие файлы открыть и что с ними
сделать, ассистент решает сам.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import llm
from agent import FileAgent

DEMO_GOALS = [
    ("Поиск использования API",
     "найди все места где используется ApiClient"),
    ("Обновление доки по коду",
     "приведи docs/api.md в соответствие с кодом api_client.py"),
    ("Генерация нового файла",
     "сгенерируй README.md для проекта"),
    ("Проверка инвариантов",
     "проверь соответствие кода правилам из CONVENTIONS.md"),
]


def show_demos() -> None:
    """Подсказка: что вообще можно попросить."""
    print("Файловый ассистент проекта yuko-sdk (ReAct-агент над project/).\n")
    print(f"Активный LLM-бэкенд: {llm.llm_available()}\n")
    print("Цель не задана. Готовые сценарии (работают и без LLM):\n")
    for i, (title, goal) in enumerate(DEMO_GOALS, 1):
        print(f"  {i}. {title}")
        print(f'     python3 main.py --goal "{goal}"')
        print()
    print("Полезные флаги:")
    print("  --dry-run       ничего не писать на диск, показать только diff")
    print("  --max-steps N   лимит шагов агента (по умолчанию 12)")
    print("  --out FILE      сохранить markdown-отчёт о работе")
    print("\nЦель можно формулировать свободно — сценарий определяется по смыслу.")


def render_report(result: dict, dry_run: bool) -> str:
    """Markdown-отчёт о прогоне: цель, шаги, diff'ы, итог."""
    out = ["# Отчёт файлового ассистента", "",
           f"**Цель:** {result['goal']}", "",
           f"**LLM-бэкенд:** {result['backend']}"
           + ("  ·  **режим:** dry-run (запись запрещена)" if dry_run else ""),
           "", f"**Шагов выполнено:** {len(result['steps'])}", "",
           "## Ход работы", ""]

    if not result["steps"]:
        out += ["_Инструменты не вызывались._", ""]

    for s in result["steps"]:
        args = ", ".join(f"{k}={_short(v)}" for k, v in (s["action_input"] or {}).items())
        out += [f"### Шаг {s['n']}: `{s['action']}({args})`", "",
                f"*Мысль:* {s['thought']}", "", "```",
                s["observation"].rstrip()[:2000], "```", ""]

    if result["writes"]:
        out += ["## Изменения файлов", ""]
        for w in result["writes"]:
            if not w["changed"]:
                out += [f"- `{w['path']}` — изменений нет.", ""]
                continue
            verb = ("будет создан" if w["created"] else "будет изменён") \
                if w["dry_run"] else ("создан" if w["created"] else "изменён")
            out += [f"### `{w['path']}` — {verb}"
                    + (" *(dry-run, на диск не записано)*" if w["dry_run"] else ""),
                    "", "```diff", w["diff"].rstrip(), "```", ""]

    out += ["## Итог", "", result["final_answer"], ""]
    return "\n".join(out)


def _short(value: object, limit: int = 80) -> str:
    """Аргумент инструмента коротко — длинный content не нужен в отчёте."""
    text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Файловый ассистент проекта: ставим цель, агент сам решает "
                    "какие инструменты звать (task34)")
    ap.add_argument("--goal", "-g",
                    help="цель, например: приведи docs/api.md в соответствие "
                         "с кодом api_client.py")
    ap.add_argument("--dry-run", action="store_true",
                    help="не писать на диск: fs_write только показывает diff")
    ap.add_argument("--max-steps", type=int, default=12,
                    help="лимит шагов агента (по умолчанию 12)")
    ap.add_argument("--out", help="сохранить markdown-отчёт в файл")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="не печатать шаги, показать только итог")
    args = ap.parse_args()

    if not args.goal:
        show_demos()
        return

    agent = FileAgent(dry_run=args.dry_run, max_steps=args.max_steps,
                      verbose=not args.quiet)
    try:
        result = agent.run(args.goal)
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

    if args.quiet:
        print(result["final_answer"])

    if args.out:
        Path(args.out).write_text(render_report(result, args.dry_run),
                                  encoding="utf-8")
        print(f"\nОтчёт записан → {args.out}")


if __name__ == "__main__":
    main()
