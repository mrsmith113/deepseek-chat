"""
Патч для memory.py — добавляем инварианты в build_context().

ИЗМЕНИТЬ в memory.py: функцию build_context()

БЫЛО:
────────────────────────────────────────────────
def build_context(agent_system, profile_prompt, long_term, working, history, user_input):
    msgs = [{"role": "system", "content": agent_system}]

    if profile_prompt:
        msgs.append({"role": "system", "content": profile_prompt})
    ...

СТАЛО:
────────────────────────────────────────────────
from invariants import build_invariant_prompt   # ← ДОБАВИТЬ в импорты

def build_context(agent_system, profile_prompt, long_term, working, history, user_input):
    msgs = [{"role": "system", "content": agent_system}]

    if profile_prompt:
        msgs.append({"role": "system", "content": profile_prompt})

    # ── НОВОЕ: инварианты идут сразу после системного промпта ──
    inv_prompt = build_invariant_prompt()
    if inv_prompt:
        msgs.append({"role": "system", "content": inv_prompt})
    # ────────────────────────────────────────────────────────────
    ...

ПОЧЕМУ именно здесь:
- build_context() — единственная точка сборки промпта для ВСЕХ агентов
- Инварианты должны быть видны агенту ВСЕГДА, независимо от агента/режима
- Размещаем после profile_prompt, чтобы профиль не перекрывал ограничения
"""
