#!/usr/bin/env python3
"""
Hornest — персонализированный CLI ассистент
Три агента: Chat / Coder / Designer
Три слоя памяти: Long-term / Working / Short-term
Профили пользователей с поддержкой сравнения
"""

import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

from db import (init_db, create_session, list_sessions, load_session,
                delete_session, update_session_agent, save_message,
                save_working, clear_working, delete_working,
                load_long_term, save_long_term, delete_long_term,
                list_profiles, load_active_profile, profiles_exist)

from agents import AGENTS, AGENT_KEYS
from profile import (profile_wizard, profile_to_system_prompt,
                     show_profiles_menu, switch_profile, PROFILE_FIELDS)
from memory import (build_context, extract_memory_suggestions,
                    show_memory, SHORT_TERM_SIZE)
from api import call_api, calc_cost, format_token_line, PRICE


# ───────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")


def check_api_key():
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key or key == "your_api_key_here":
        print("\n  ⚠️  API ключ не найден в .env")
        key = input("  Введи DEEPSEEK_API_KEY: ").strip()
        if key:
            os.environ["DEEPSEEK_API_KEY"] = key
            # сохраняем в .env
            try:
                with open(".env", "w") as f:
                    f.write(f"DEEPSEEK_API_KEY={key}\n")
                print("  ✅ Ключ сохранён в .env\n")
            except Exception:
                print("  ✅ Ключ задан для текущей сессии\n")
        else:
            print("  ❌ Без ключа работа невозможна.")
            sys.exit(1)


def show_help():
    print("""
Команды:
  /agent    — сменить агента (Chat / Coder / Designer)
  /profile  — управление профилями
  /compare  — один вопрос × все агенты × два профиля
  /memory   — все слои памяти
  /remember — сохранить в долговременную память
  /forget   — удалить из долговременной памяти
  /working  — управление рабочей памятью
  /tokens   — статистика токенов с разбивкой кэша
  /sessions — сессии
  /reset    — сбросить краткосрочную и рабочую память
  /exit     — выход
""")


SHORTCUTS = {
    "1": "/agent", "2": "/profile", "3": "/compare",
    "4": "/memory", "5": "/remember", "6": "/forget",
    "7": "/working", "8": "/tokens", "9": "/sessions",
    "0": "/reset", "x": "/exit", "h": "/help",
}


# ───────────────────────────────────────────
# Сессии
# ───────────────────────────────────────────

def choose_or_create_session():
    sessions = list_sessions()
    if not sessions:
        print("\n  Сессий нет. Создаём новую.")
        name = input("  Название (Enter = 'Сессия 1'): ").strip() or "Сессия 1"
        return create_session(name), "chat", [], [], {}

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<22} {'Агент':<14} {'Сообщ.'}")
    print(f"  {'-'*4} {'-'*22} {'-'*14} {'-'*6}")
    for sid, name, agent_key, _, mc in sessions:
        aname = AGENTS.get(agent_key, AGENTS["chat"])["name"]
        print(f"  {sid:<4} {name:<22} {aname:<14} {mc}")

    print("\n  [N] Новая   [D] Удалить")
    valid = [str(s[0]) for s in sessions]

    while True:
        choice = input("\n  Выбери ID или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("  Название: ").strip() or f"Сессия {len(sessions)+1}"
            return create_session(name), "chat", [], [], {}
        elif choice == "D":
            did = input("  ID для удаления: ").strip()
            if did in valid:
                delete_session(int(did))
                print("  ✅ Удалено.")
                return choose_or_create_session()
        elif choice in valid:
            sid = int(choice)
            agent_key, history, token_log, working = load_session(sid)
            return sid, agent_key, history, token_log, working
        else:
            print("  Неверный выбор.")


# ───────────────────────────────────────────
# Сравнение: все агенты × два профиля
# ───────────────────────────────────────────

def compare_agents_profiles(history, working, long_term):
    divider("🔄 СРАВНЕНИЕ: Агенты × Профили")

    q = input("  Вопрос для сравнения: ").strip()
    if not q:
        return

    # Профиль 1 — активный
    pname1, p1 = load_active_profile()
    if not p1:
        print("  Нет активного профиля. Создай профиль через /profile\n")
        return
    print(f"\n  Профиль 1: '{pname1}' (активный)")

    # Профиль 2 — выбираем
    print("\n  Выбери второй профиль:")
    profiles = list_profiles()
    if len(profiles) < 2:
        print("  Нужен второй профиль. Создай через /profile → Новый.\n")
        return
    show_profiles_menu()
    valid = {str(p[0]): p for p in profiles}
    while True:
        ch = input("  ID второго профиля: ").strip()
        if ch in valid:
            import json as _json
            p2_row = valid[ch]
            pname2 = p2_row[1]
            p2     = _json.loads(p2_row[2])
            break
        print("  Неверный ID.")

    prompt1 = profile_to_system_prompt(p1)
    prompt2 = profile_to_system_prompt(p2)

    print(f"\n  Запрашиваю {len(AGENTS)*2} ответов...\n")

    results = {}
    for agent_key, agent in AGENTS.items():
        results[agent_key] = {}
        for pname, prompt in [(pname1, prompt1), (pname2, prompt2)]:
            msgs = build_context(agent["system"], prompt, long_term, working, history, q)
            r    = call_api(msgs)
            results[agent_key][pname] = r

    divider(f"ВОПРОС: {q}")
    for agent_key, agent in AGENTS.items():
        print(f"\n  {agent['name']}")
        print(f"  {'─'*56}")
        for pname in [pname1, pname2]:
            r   = results[agent_key][pname]
            tok = r.get("usage", {}).get("prompt_tokens", 0)
            ans = r.get("answer") or "❌ Ошибка"
            if len(ans) > 300:
                ans = ans[:300] + "..."
            print(f"\n  👤 [{pname}] ({tok} tok):")
            print(f"  {ans}")
    print()


# ───────────────────────────────────────────
# Статистика токенов
# ───────────────────────────────────────────

def show_tokens(token_log, session_id):
    divider("📊 СТАТИСТИКА ТОКЕНОВ")
    total_miss = total_cached = total_out = total_cost = 0
    print(f"\n  {'#':<4} {'Агент':<14} {'Кэш':>8} {'Новые':>8} {'Выход':>8} {'$':>10}")
    print(f"  {'-'*4} {'-'*14} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    req_num = 0
    for r, ct, it, ot, ca in token_log:
        if r == "user" and it > 0:
            req_num += 1
            miss = it - ca
            cost, _, _, _ = calc_cost({"prompt_tokens": it,
                                        "prompt_cache_hit_tokens": ca,
                                        "completion_tokens": ot})
            total_miss   += miss
            total_cached += ca
            total_out    += ot
            total_cost   += cost
            # ищем агент следующего сообщения
            print(f"  {req_num:<4} {'—':<14} {ca:>8,} {miss:>8,} {ot:>8,} {cost:>10.6f}")

    print(f"  {'─'*56}")
    print(f"  {'ИТОГО':<18} {total_cached:>8,} {total_miss:>8,} {total_out:>8,} {total_cost:>10.6f}")

    print(f"\n  Цены ($ за 1M):")
    print(f"  Новые токены: ${PRICE['input']}  |  Кэш: ${PRICE['cached']}  |  Выход: ${PRICE['output']}")
    savings = total_cached / 1_000_000 * (PRICE["input"] - PRICE["cached"])
    print(f"  💰 Экономия от кэша: ${savings:.6f}\n")


# ───────────────────────────────────────────
# Авто-предложение памяти
# ───────────────────────────────────────────

def handle_memory_suggestions(suggestions, session_id, long_term, working):
    if not suggestions:
        return

    print(f"\n  💡 Предлагаю сохранить:")
    for i, s in enumerate(suggestions, 1):
        layer = "🟢 долговременная" if s["layer"] == "long" else "🟡 рабочая"
        print(f"     [{i}] \"{s['key']}: {s['value']}\" → {layer}")

    print("  Выбор (1 2 3... / all / Enter): ", end="")
    choice = input().strip().lower()
    if not choice:
        return

    indices = list(range(len(suggestions))) if choice == "all" else [
        int(c)-1 for c in choice.split() if c.isdigit() and 1 <= int(c) <= len(suggestions)
    ]

    for i in indices:
        s = suggestions[i]
        if s["layer"] == "long":
            cat = input(f"  Категория для '{s['key']}' (profile/decision/knowledge/general): ").strip()
            cat = cat if cat in ["profile", "decision", "knowledge", "general"] else "general"
            save_long_term(s["key"], s["value"], cat)
            long_term[s["key"]] = (s["value"], cat)
            print(f"  ✅ → 🟢 [{cat}]: {s['key']}")
        else:
            save_working(session_id, s["key"], s["value"])
            working[s["key"]] = s["value"]
            print(f"  ✅ → 🟡 рабочая: {s['key']}")


# ───────────────────────────────────────────
# Главный цикл
# ───────────────────────────────────────────

def main():
    divider("🐝 HORNEST — Персонализированный ассистент")

    check_api_key()
    init_db()

    # Профиль
    if not profiles_exist():
        print("\n  Первый запуск — настроим профиль!\n")
        profile_name, profile = profile_wizard()
    else:
        profile_name, profile = load_active_profile()
        if not profile:
            profile_name, profile = profile_wizard()

    # Сессия
    session_id, agent_key, history, token_log, working = choose_or_create_session()

    # Long-term
    lt_rows   = load_long_term()
    long_term = {k: (v, cat) for k, v, cat in lt_rows}

    agent = AGENTS.get(agent_key, AGENTS["chat"])

    print(f"\n  👤 Профиль: {profile_name} | {profile.get('name','')}")
    print(f"  🤖 Агент:   {agent['name']}")
    print(f"  🟢 Long-term: {len(long_term)} | 🟡 Working: {len(working)} | 🔵 Short-term: {len(history)}")
    print("  Введи /help для справки.\n")

    while True:
        try:
            user_input = input(f"[{agent['name']}] Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Выход.")
            break

        if not user_input:
            continue

        user_input = SHORTCUTS.get(user_input.lower(), user_input)

        # ── Команды ─────────────────────────────

        if user_input == "/exit":
            print("\n  Пока!\n")
            break

        elif user_input == "/help":
            show_help()

        elif user_input == "/agent":
            print("\n  Выбери агента:")
            for i, key in enumerate(AGENT_KEYS, 1):
                mark = " ◀" if key == agent_key else ""
                print(f"  [{i}] {AGENTS[key]['name']}{mark}")
            ch = input("  Выбор [1-3]: ").strip()
            if ch.isdigit() and 1 <= int(ch) <= len(AGENT_KEYS):
                agent_key = AGENT_KEYS[int(ch)-1]
                agent     = AGENTS[agent_key]
                update_session_agent(session_id, agent_key)
                print(f"\n  ✅ Агент: {agent['name']}\n")

        elif user_input == "/profile":
            print("\n  Управление профилями:")
            print("  [1] Показать профили")
            print("  [2] Создать новый профиль")
            print("  [3] Переключить активный профиль")
            ch = input("  Выбор: ").strip()
            if ch == "1":
                show_profiles_menu()
            elif ch == "2":
                profile_name, profile = profile_wizard()
            elif ch == "3":
                pn, pd = switch_profile()
                if pd:
                    profile_name, profile = pn, pd

        elif user_input == "/compare":
            compare_agents_profiles(history, working, long_term)

        elif user_input == "/memory":
            show_memory(long_term, working, history)

        elif user_input == "/remember":
            key   = input("  Ключ: ").strip()
            value = input("  Значение: ").strip()
            cat   = input("  Категория (profile/decision/knowledge/general): ").strip()
            cat   = cat if cat in ["profile", "decision", "knowledge", "general"] else "general"
            save_long_term(key, value, cat)
            long_term[key] = (value, cat)
            print(f"  ✅ Сохранено в 🟢 [{cat}]: {key}\n")

        elif user_input == "/forget":
            if not long_term:
                print("\n  Долговременная память пуста.\n")
            else:
                keys = list(long_term.keys())
                for i, k in enumerate(keys, 1):
                    v, cat = long_term[k]
                    print(f"  [{i}] [{cat}] {k}: {v}")
                ch = input("  Удалить номер (Enter = отмена): ").strip()
                if ch.isdigit() and 1 <= int(ch) <= len(keys):
                    k = keys[int(ch)-1]
                    delete_long_term(k)
                    del long_term[k]
                    print(f"  ✅ Удалено: {k}\n")

        elif user_input == "/working":
            print("\n  [1] Показать  [2] Добавить  [3] Удалить запись  [4] Очистить всё")
            ch = input("  Выбор: ").strip()
            if ch == "1":
                if working:
                    for k, v in working.items():
                        print(f"  • {k}: {v}")
                else:
                    print("  Рабочая память пуста.")
                print()
            elif ch == "2":
                k = input("  Ключ: ").strip()
                v = input("  Значение: ").strip()
                save_working(session_id, k, v)
                working[k] = v
                print(f"  ✅ Сохранено: {k}\n")
            elif ch == "3":
                if working:
                    keys = list(working.keys())
                    for i, k in enumerate(keys, 1):
                        print(f"  [{i}] {k}: {working[k]}")
                    idx = input("  Номер: ").strip()
                    if idx.isdigit() and 1 <= int(idx) <= len(keys):
                        k = keys[int(idx)-1]
                        delete_working(session_id, k)
                        del working[k]
                        print(f"  ✅ Удалено: {k}\n")
            elif ch == "4":
                clear_working(session_id)
                working.clear()
                print("  🗑️  Рабочая память очищена.\n")

        elif user_input == "/tokens":
            show_tokens(token_log, session_id)

        elif user_input == "/sessions":
            sessions = list_sessions()
            divider("СЕССИИ")
            for s_id, name, ak, _, mc in sessions:
                mark  = " ◀" if s_id == session_id else ""
                aname = AGENTS.get(ak, AGENTS["chat"])["name"]
                print(f"  [{s_id}] {name} | {aname} | {mc} сообщ.{mark}")
            print("\n  [N] Новая  [Enter] Остаться")
            valid = [str(s[0]) for s in sessions]
            sw = input("  Переключиться на ID или [N]: ").strip().upper()
            if sw == "N":
                new_name = input("  Название: ").strip() or f"Сессия {len(sessions)+1}"
                session_id = create_session(new_name)
                agent_key  = "chat"
                agent      = AGENTS["chat"]
                history    = []
                token_log  = []
                working    = {}
                print(f"\n  ✅ Новая сессия: {new_name}\n")
            elif sw in valid and int(sw) != session_id:
                session_id = int(sw)
                ak2, hist2, tlog2, work2 = load_session(session_id)
                agent_key = ak2
                agent     = AGENTS.get(ak2, AGENTS["chat"])
                history   = hist2
                token_log = tlog2
                working   = work2
                print(f"\n  ✅ Сессия {session_id} | {agent['name']}\n")

        elif user_input == "/reset":
            history   = []
            clear_working(session_id)
            working   = {}
            from db import get_conn
            conn = get_conn()
            conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            conn.commit()
            conn.close()
            print("  🗑️  Краткосрочная и рабочая память сброшены. Long-term сохранена.\n")

        # ── Обычное сообщение ─────────────────────

        else:
            profile_prompt = profile_to_system_prompt(profile) if profile else ""
            messages = build_context(
                agent["system"], profile_prompt,
                long_term, working, history, user_input
            )
            result = call_api(messages)

            if result["error"]:
                print(f"\n  ❌ Ошибка: {result['error'].get('message', result['error'])}\n")
                continue

            answer     = result["answer"]
            usage      = result.get("usage", {})
            input_tok  = usage.get("prompt_tokens", 0)
            output_tok = usage.get("completion_tokens", 0)
            cached_tok = usage.get("prompt_cache_hit_tokens", 0)

            history.append({"role": "user",      "content": user_input})
            history.append({"role": "assistant",  "content": answer})

            save_message(session_id, agent_key, "user",      user_input,
                         input_tok, 0, cached_tok)
            save_message(session_id, agent_key, "assistant", answer,
                         0, output_tok, 0)
            token_log.append(("user",      user_input, input_tok,  0,          cached_tok))
            token_log.append(("assistant", answer,     0,          output_tok, 0))

            print(f"\n  {agent['name']}:\n{answer}\n")
            print(format_token_line(usage, agent["name"]))

            # авто-предложение памяти
            print("\n  ⏳ Анализирую...", end="\r")
            suggestions = extract_memory_suggestions(user_input, answer, call_api)
            if suggestions:
                handle_memory_suggestions(suggestions, session_id, long_term, working)
            else:
                print("  " + " "*20)  # очищаем строку
            print()


if __name__ == "__main__":
    main()
