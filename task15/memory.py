import json
from db import (load_long_term, save_long_term, delete_long_term,
                save_working, clear_working, delete_working)
from invariants import build_invariant_prompt

SHORT_TERM_SIZE = 6  # пар сообщений в краткосрочной


def build_context(agent_system, profile_prompt, long_term,
                  working, history, user_input):
    """Собираем полный контекст для API запроса"""
    msgs = [{"role": "system", "content": agent_system}]

    if profile_prompt:
        msgs.append({"role": "system", "content": profile_prompt})

    # ⛔ Инварианты — жёсткие ограничения агента
    inv_prompt = build_invariant_prompt()
    if inv_prompt:
        msgs.append({"role": "system", "content": inv_prompt})

    # 🟢 Long-term
    if long_term:
        lt_text = "\n".join(
            f"• [{cat}] {k}: {v}" for k, (v, cat) in long_term.items()
        )
        msgs.append({"role": "system",
                     "content": f"🟢 Долговременная память:\n{lt_text}"})

    # 🟡 Working
    if working:
        wm_text = "\n".join(f"• {k}: {v}" for k, v in working.items())
        msgs.append({"role": "system",
                     "content": f"🟡 Рабочая память (текущая задача):\n{wm_text}"})

    # 🔵 Short-term — последние N пар
    tail = history[-(SHORT_TERM_SIZE * 2):]
    msgs += tail
    msgs.append({"role": "user", "content": user_input})
    return msgs


def extract_memory_suggestions(user_input, answer, call_api_fn):
    """Просим модель предложить что сохранить"""
    prompt = (
        f"Из этого обмена извлеки важные факты для запоминания.\n"
        f"Пользователь: {user_input}\nАссистент: {answer}\n\n"
        f"Верни JSON список: "
        f"[{{\"key\":\"ключ\",\"value\":\"значение\",\"layer\":\"long\" или \"working\"}}]\n"
        f"long — профиль, решения, постоянные знания.\n"
        f"working — детали текущей задачи, временные данные.\n"
        f"Если нечего запоминать — верни [].\n"
        f"Только JSON, без пояснений."
    )
    r = call_api_fn([{"role": "user", "content": prompt}], temperature=0, max_tokens=300)
    if r.get("answer"):
        try:
            text = r["answer"].strip().replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except Exception:
            pass
    return []


def show_memory(long_term, working, history):
    print("\n" + "="*60)
    print("  ПАМЯТЬ АГЕНТА")
    print("="*60)

    print("\n  🟢 ДОЛГОВРЕМЕННАЯ (все сессии):")
    if long_term:
        for k, (v, cat) in long_term.items():
            print(f"     [{cat}] {k}: {v}")
    else:
        print("     пусто")

    print("\n  🟡 РАБОЧАЯ (эта сессия):")
    if working:
        for k, v in working.items():
            print(f"     {k}: {v}")
    else:
        print("     пусто")

    print(f"\n  🔵 КРАТКОСРОЧНАЯ (последние {SHORT_TERM_SIZE} пар):")
    tail = history[-(SHORT_TERM_SIZE * 2):]
    if tail:
        for m in tail:
            label   = "Ты" if m["role"] == "user" else "Агент"
            preview = m["content"][:80].replace("\n", " ")
            ellipsis = "..." if len(m["content"]) > 80 else ""
            print(f"     [{label}] {preview}{ellipsis}")
    else:
        print("     пусто")
    print()
