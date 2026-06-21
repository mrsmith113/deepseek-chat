"""
InvariantGuard — агент-контролёр переходов между этапами.

Проверяет артефакт перед каждым переходом:
1. Есть ли артефакт вообще? (нельзя перейти без результата)
2. Не нарушает ли артефакт инварианты?

При нарушении — автоматический rework на текущий этап с комментарием.
"""

from invariants import build_invariant_prompt, list_invariants

# ── Системный промпт Guard-агента ─────────

GUARD_SYSTEM = """Ты InvariantGuard — строгий контролёр переходов между этапами задачи.

Твоя единственная задача: проверить, нарушает ли предложенный артефакт (результат этапа) 
какой-либо из инвариантов системы.

Правила ответа:
- Если нарушений НЕТ — ответь строго: [GUARD:OK]
- Если нарушение ЕСТЬ — ответь строго: [GUARD:BLOCK]
  Затем с новой строки объясни:
  - Какой инвариант нарушен (название)
  - Где именно в артефакте нарушение
  - Что нужно исправить

Будь конкретен и краток. Не предлагай обойти инварианты."""


def run_guard(artifact_text, task_title, call_api_fn):
    """
    Запускает InvariantGuard на артефакт.
    
    Возвращает:
        ("ok", "")             — переход разрешён
        ("block", "причина")   — переход заблокирован, причина для rework
        ("skip", "")           — инвариантов нет, проверка не нужна
    """
    # Если инвариантов нет — пропускаем проверку
    if not list_invariants():
        return "skip", ""

    inv_prompt = build_invariant_prompt()

    msgs = [
        {"role": "system", "content": GUARD_SYSTEM},
        {"role": "system", "content": inv_prompt},
        {"role": "user", "content": (
            f"Задача: {task_title}\n\n"
            f"Артефакт для проверки:\n{artifact_text}\n\n"
            f"Проверь артефакт на соответствие инвариантам. "
            f"Начни ответ с [GUARD:OK] или [GUARD:BLOCK]."
        )}
    ]

    r = call_api_fn(msgs)
    answer = r.get("answer", "")

    if "[GUARD:OK]" in answer:
        return "ok", ""
    elif "[GUARD:BLOCK]" in answer:
        # Вырезаем объяснение после [GUARD:BLOCK]
        reason = answer.replace("[GUARD:BLOCK]", "").strip()
        return "block", reason
    else:
        # Непонятный ответ — пропускаем (не блокируем на всякий случай)
        return "skip", ""


def show_guard_result(result, reason, from_state, to_state):
    """Красивый вывод результата проверки"""
    from task_state import STATE_META
    from_label = STATE_META.get(from_state, {}).get("label", from_state)
    to_label   = STATE_META.get(to_state,   {}).get("label", to_state)

    if result == "ok":
        print(f"\n  ⛔→✅ InvariantGuard: артефакт прошёл проверку")
        print(f"  Переход разрешён: {from_label} → {to_label}\n")

    elif result == "block":
        print(f"\n  {'═'*54}")
        print(f"  ⛔ InvariantGuard: ПЕРЕХОД ЗАБЛОКИРОВАН")
        print(f"  {from_label} → {to_label} — ЗАПРЕЩЕНО")
        print(f"  {'─'*54}")
        print(f"  {reason}")
        print(f"  {'─'*54}")
        print(f"  🔄 Автоматический откат на: {from_label}")
        print(f"  Исправь артефакт и повтори.\n")

    elif result == "skip":
        pass  # Инвариантов нет — тихо пропускаем
