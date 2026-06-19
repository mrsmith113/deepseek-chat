"""
Патч для hornest.py — добавляем роутинг команд /inv и инициализацию инвариантов.

═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 1: Импорты (в начало файла, после from api import ...)
═══════════════════════════════════════════════════════

from invariants import (
    init_invariant_table, show_invariants,
    add_invariant_interactive, remove_invariant_interactive,
    check_text_against_invariants, detect_conflict,
    build_invariant_prompt
)


═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 2: Инициализация в main() — после init_task_tables()
═══════════════════════════════════════════════════════

    init_db()
    init_task_tables()
    init_invariant_table()   # ← ДОБАВИТЬ


═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 3: SHORTCUTS — добавить 'i': '/inv'
═══════════════════════════════════════════════════════

SHORTCUTS = {
    "1": "/agent", "2": "/profile", "3": "/compare",
    "4": "/memory", "5": "/remember", "6": "/forget",
    "7": "/working", "8": "/tokens", "9": "/sessions",
    "0": "/reset", "x": "/exit", "h": "/help", "t": "/task status",
    "i": "/inv",   # ← ДОБАВИТЬ
}


═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 4: show_help() — добавить в список команд
═══════════════════════════════════════════════════════

Добавить в текст справки:
  /inv      — управление инвариантами (ограничения агента)
  /inv list — показать все инварианты
  /inv add  — добавить инвариант
  /inv rm   — удалить инвариант
  /inv check <текст> — проверить текст на конфликт


═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 5: Роутинг /inv — добавить в главный цикл while True:
             ПОСЛЕ блока /task и ПЕРЕД elif user_input == "/exit":
═══════════════════════════════════════════════════════

        elif user_input.startswith("/inv"):
            parts = user_input.split(None, 2)
            sub   = parts[1] if len(parts) > 1 else "list"
            arg   = parts[2] if len(parts) > 2 else ""

            if sub == "list" or sub == "":
                show_invariants()

            elif sub == "add":
                add_invariant_interactive()

            elif sub in ("rm", "remove", "del"):
                remove_invariant_interactive()

            elif sub == "check":
                if arg:
                    check_text_against_invariants(arg, call_api)
                else:
                    text = input("  Текст для проверки: ").strip()
                    if text:
                        check_text_against_invariants(text, call_api)

            else:
                print("\\n  Команды: /inv list | /inv add | /inv rm | /inv check <текст>\\n")


═══════════════════════════════════════════════════════
ИЗМЕНЕНИЕ 6: Детект конфликта в основном цикле ответа
             В блоке где выводится r.get("answer") — после print(answer)
═══════════════════════════════════════════════════════

НАЙТИ в коде (блок обычного диалога, где печатается ответ агента):
────────────────────────────────────────
            answer = r.get("answer", "")
            if answer:
                print(f"\\n  {agent['name']}: {answer}\\n")
────────────────────────────────────────

ИЗМЕНИТЬ на:
────────────────────────────────────────
            answer = r.get("answer", "")
            if answer:
                # Проверяем: агент обнаружил конфликт с инвариантом?
                conflict = detect_conflict(answer)
                if conflict:
                    print(f"\\n  ⛔ [{agent['name']}] КОНФЛИКТ С ИНВАРИАНТОМ: {conflict}")
                    print(f"  {'─'*54}")

                print(f"\\n  {agent['name']}: {answer}\\n")
────────────────────────────────────────

ЗАЧЕМ: чтобы конфликт выделялся визуально даже до того, как пользователь
прочтёт весь ответ агента.
"""
