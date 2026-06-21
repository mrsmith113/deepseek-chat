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

from agents import AGENTS, AGENT_KEYS, ALL_AGENTS, ALL_AGENT_KEYS, MANAGER_AGENT
from task_state import (init_task_tables, create_task, get_active_task, list_tasks,
                        update_task_state, pause_task, resume_task, close_task,
                        resume_task_by_id, save_task_message, load_task_history,
                        build_task_messages, show_task_status, next_state,
                        STATE_META, STATES, detect_signal, clean_answer,
                        run_parallel_subagents, merge_subagent_results, demo_parallel)
from pipeline import (PipelineRunner, PIPELINE_AGENTS, run_pipeline_parallel,
                      show_parallel_results, merge_for_orchestrator, load_artifacts)
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
  /agent    — сменить агента (Chat / Coder / Designer / Manager)
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

Команды Manager агента (🗂):
  /task new <название>  — создать задачу
  /task new <название> --confirm  — с подтверждением каждого перехода
  /task status          — текущий этап и прогресс
  /task next            — перейти на следующий этап
  /task pause           — поставить на паузу
  /task resume          — продолжить задачу
  /task list            — все задачи сессии
  /task close           — завершить задачу досрочно
  /task rework          — откатиться на предыдущий этап с комментарием
  /task parallel        — запустить параллельных субагентов на текущем этапе
  /task swarm           — параллельный запуск субагентов в режиме пайплайна
  /task artifacts       — показать артефакты всех этапов
""")


SHORTCUTS = {
    "1": "/agent", "2": "/profile", "3": "/compare",
    "4": "/memory", "5": "/remember", "6": "/forget",
    "7": "/working", "8": "/tokens", "9": "/sessions",
    "0": "/reset", "x": "/exit", "h": "/help", "t": "/task status",
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
    init_task_tables()

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

    agent = ALL_AGENTS.get(agent_key, ALL_AGENTS["chat"])

    # Pipeline runner — активируется когда агент Manager
    pipeline_runner = None

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

        if user_input.startswith("/task"):
            if agent_key != "manager":
                print("\n  ⚠️  Команды /task доступны только для агента 🗂 Manager. Используй /agent\n")
            else:
                parts = user_input.split(None, 2)
                sub   = parts[1] if len(parts) > 1 else ""
                arg   = parts[2] if len(parts) > 2 else ""

                if sub == "new":
                    confirm = "--confirm" in arg
                    title   = arg.replace("--confirm", "").strip() or input("  Название задачи: ").strip()
                    if title:
                        task_id     = create_task(session_id, title, confirm=confirm)
                        active_task = get_active_task(session_id)
                        mode        = " [режим подтверждений]" if confirm else ""
                        profile_prompt_tmp = profile_to_system_prompt(profile) if profile else ""
                        pipeline_runner = PipelineRunner(active_task, profile_prompt_tmp, call_api)
                        print(f"\n  ✅ Задача создана: '{title}'{mode}")
                        print(f"  Этап: {STATE_META['planning']['label']} | Агент: {PIPELINE_AGENTS['planning']['name']}")
                        print(f"  Начни описывать задачу.\n")

                elif sub == "status":
                    active_task = get_active_task(session_id)
                    if active_task:
                        show_task_status(active_task)
                    else:
                        print("\n  Нет активной задачи. Создай: /task new <название>\n")

                elif sub == "next":
                    active_task = get_active_task(session_id)
                    if not active_task:
                        print("\n  Нет активной задачи.\n")
                    elif active_task["state"] == "done":
                        print("\n  Задача уже завершена.\n")
                    else:
                        old_st    = active_task["state"]
                        if pipeline_runner:
                            new_state = pipeline_runner.force_transition(active_task["id"])
                        else:
                            new_state = next_state(old_st)
                            update_task_state(active_task["id"], new_state)
                        active_task = get_active_task(session_id)
                        if pipeline_runner and active_task:
                            pipeline_runner.task = active_task
                            pipeline_runner.show_handoff(old_st, new_state)
                        new_agent = PIPELINE_AGENTS.get(new_state, {}).get("name", new_state)
                        print(f"  ✅ Принудительный переход → {new_agent}\n")
                        if new_state == "done":
                            print("  🏁 Задача завершена!\n")

                elif sub == "pause":
                    active_task = get_active_task(session_id)
                    if active_task:
                        pause_task(active_task["id"])
                        print(f"\n  ⏸ Задача '{active_task['title']}' поставлена на паузу.")
                        print(f"  Этап сохранён: {STATE_META[active_task['state']]['label']}")
                        print(f"  Продолжи позже: /task resume\n")
                    else:
                        print("\n  Нет активной задачи.\n")

                elif sub == "resume":
                    active_task = get_active_task(session_id)
                    if active_task and active_task["is_paused"]:
                        resume_task(active_task["id"])
                        active_task = get_active_task(session_id)
                        pipeline_runner = PipelineRunner(active_task, profile_to_system_prompt(profile) if profile else "", call_api)
                        cur_agent = pipeline_runner.current_agent()
                        print(f"\n  ▶️  Продолжаем: '{active_task['title']}'")
                        print(f"  Агент: {cur_agent['name']}")
                        show_task_status(active_task)
                    else:
                        # показываем список задач для выбора
                        tasks = list_tasks(session_id)
                        paused = [(t[0], t[1], t[2]) for t in tasks if t[4]]
                        if paused:
                            print("\n  Задачи на паузе:")
                            for tid, ttitle, tstate in paused:
                                print(f"  [{tid}] {ttitle} | {STATE_META[tstate]['label']}")
                            ch = input("  ID задачи для продолжения: ").strip()
                            if ch.isdigit():
                                resume_task_by_id(session_id, int(ch))
                                active_task = get_active_task(session_id)
                                if active_task:
                                    print(f"\n  ▶️  Продолжаем: '{active_task['title']}'")
                                    show_task_status(active_task)
                        else:
                            print("\n  Нет задач на паузе.\n")

                elif sub == "list":
                    tasks = list_tasks(session_id)
                    if tasks:
                        print()
                        for tid, ttitle, tstate, is_active, is_paused, created in tasks:
                            active_mark = " ◀ активная" if is_active else ""
                            pause_mark  = " ⏸" if is_paused else ""
                            slabel      = STATE_META.get(tstate, {}).get("label", tstate)
                            print(f"  [{tid}] {ttitle} | {slabel}{pause_mark}{active_mark}")
                        print()
                    else:
                        print("\n  Задач нет. Создай: /task new <название>\n")

                elif sub == "parallel":
                    active_task = get_active_task(session_id)
                    if not active_task:
                        print("\n  Нет активной задачи.\n")
                    else:
                        merged = demo_parallel(active_task, call_api)
                        # передаём результат оркестратору
                        profile_prompt = profile_to_system_prompt(profile) if profile else ""
                        orch_msgs = build_task_messages(
                            active_task, agent["system"], profile_prompt,
                            f"Вот результаты параллельных субагентов:\n{merged}\nСделай сводный вывод."
                        )
                        r = call_api(orch_msgs)
                        if r.get("answer"):
                            print(f"\n  🗂 Оркестратор:\n{clean_answer(r['answer'])}\n")
                            save_task_message(active_task["id"], active_task["state"],
                                              "assistant", r["answer"])

                elif sub == "artifacts":
                    active_task = get_active_task(session_id)
                    if not active_task:
                        print("\n  Нет активной задачи.\n")
                    else:
                        artifacts = load_artifacts(active_task["id"])
                        if artifacts:
                            print(f"\n  📋 Артефакты задачи '{active_task['title']}':")
                            for stage, content_art in artifacts.items():
                                label = STATE_META.get(stage, {}).get("label", stage)
                                print(f"\n  {label}:")
                                print(f"  {content_art[:300]}{'...' if len(content_art)>300 else ''}")
                            print()
                        else:
                            print("\n  Артефактов пока нет.\n")

                elif sub == "swarm":
                    active_task = get_active_task(session_id)
                    if not active_task:
                        print("\n  Нет активной задачи.\n")
                    else:
                        state = active_task["state"]
                        print(f"\n  Настроим параллельных субагентов для этапа {STATE_META[state]['label']}")
                        print("  Сколько субагентов запустить? [2-4]: ", end="")
                        n_str = input().strip()
                        n = int(n_str) if n_str.isdigit() and 2 <= int(n_str) <= 4 else 2

                        subagents = []
                        for i in range(n):
                            print(f"\n  Субагент {i+1}:")
                            name   = input(f"  Имя (например 'Юрист'): ").strip() or f"Субагент {i+1}"
                            role   = input(f"  Роль (системный промпт кратко): ").strip() or "Ты полезный ассистент."
                            q      = input(f"  Вопрос/задача: ").strip() or active_task["title"]
                            subagents.append({"name": name, "system": role, "question": q})

                        results = run_pipeline_parallel(active_task, subagents, call_api)
                        show_parallel_results(results)

                        # Передаём оркестратору
                        merged = merge_for_orchestrator(active_task["title"], results)
                        if pipeline_runner:
                            orch_msgs = pipeline_runner.build_messages(
                                f"Вот результаты параллельных субагентов:\n{merged}\nСделай сводный вывод и определи следующие шаги."
                            )
                            r = call_api(orch_msgs)
                            if r.get("answer"):
                                ans_clean = clean_answer(r["answer"])
                                print(f"\n  {PIPELINE_AGENTS.get(state, {}).get('name','Агент')} (оркестратор):")
                                print(f"  {ans_clean}\n")
                                save_task_message(active_task["id"], state, "assistant", r["answer"])

                elif sub == "rework":
                    active_task = get_active_task(session_id)
                    if not active_task:
                        print("\n  Нет активной задачи.\n")
                    elif active_task["state"] == "planning":
                        print("\n  Уже на первом этапе — некуда откатываться.\n")
                    else:
                        # Показываем доступные этапы для отката
                        cur_idx = STATES.index(active_task["state"])
                        print(f"\n  Откат с этапа: {STATE_META[active_task['state']]['label']}")
                        print(f"  На какой этап откатиться?")
                        for i in range(cur_idx):
                            print(f"  [{i+1}] {STATE_META[STATES[i]]['label']}")
                        ch = input("  Выбор (Enter = предыдущий): ").strip()
                        if ch.isdigit() and 1 <= int(ch) <= cur_idx:
                            target_state = STATES[int(ch)-1]
                        else:
                            target_state = STATES[cur_idx - 1]

                        comment = input("  Что нужно переделать? (комментарий агенту): ").strip()
                        if not comment:
                            comment = "Нужна доработка, вернись к этому этапу."

                        # Удаляем старые сообщения откатного этапа — агент начнёт чисто
                        from db import get_conn as _get_conn
                        _conn = _get_conn()
                        _conn.execute(
                            "DELETE FROM task_messages WHERE task_id=? AND state=? AND role IN ('user','assistant')",
                            (active_task["id"], target_state)
                        )
                        _conn.commit()
                        _conn.close()

                        # Сохраняем rework как artifact чтобы pipeline подхватил
                        from pipeline import save_artifact as _save_artifact
                        rework_note = (
                            f"ЗАПРОС НА ДОРАБОТКУ от пользователя:\n"
                            f"{comment}\n\n"
                            f"Внимательно изучи этот комментарий и переработай результат этапа."
                        )
                        _save_artifact(active_task["id"], f"{target_state}_rework", rework_note)

                        # Откатываем state, снимаем паузу
                        update_task_state(active_task["id"], target_state)
                        resume_task(active_task["id"])
                        active_task = get_active_task(session_id)

                        # Пересоздаём runner
                        pipeline_runner = PipelineRunner(
                            active_task,
                            profile_to_system_prompt(profile) if profile else "",
                            call_api
                        )
                        cur_agent = pipeline_runner.current_agent()

                        print(f"\n  🔄 Откат на: {STATE_META[target_state]['label']}")
                        print(f"  Агент: {cur_agent['name']}")
                        print(f"  История этапа очищена. Комментарий передан.")
                        print(f"  Напиши агенту что нужно сделать — он знает контекст.\n")

                elif sub == "close":
                    active_task = get_active_task(session_id)
                    if active_task:
                        close_task(active_task["id"])
                        print(f"\n  ✅ Задача '{active_task['title']}' закрыта.\n")
                    else:
                        print("\n  Нет активной задачи.\n")
                else:
                    print("\n  Команды: new / status / next / pause / resume / list / close\n")

        elif user_input == "/exit":
            print("\n  Пока!\n")
            break

        elif user_input == "/help":
            show_help()

        elif user_input == "/agent":
            print("\n  Выбери агента:")
            for i, key in enumerate(ALL_AGENT_KEYS, 1):
                mark = " ◀" if key == agent_key else ""
                print(f"  [{i}] {ALL_AGENTS[key]['name']}{mark}")
            ch = input(f"  Выбор [1-{len(ALL_AGENT_KEYS)}]: ").strip()
            if ch.isdigit() and 1 <= int(ch) <= len(ALL_AGENT_KEYS):
                agent_key = ALL_AGENT_KEYS[int(ch)-1]
                agent     = ALL_AGENTS[agent_key]
                update_session_agent(session_id, agent_key)
                if agent_key == "manager":
                    active_task = get_active_task(session_id)
                    profile_prompt_tmp = profile_to_system_prompt(profile) if profile else ""
                    pipeline_runner = PipelineRunner(active_task, profile_prompt_tmp, call_api) if active_task else None
                    if active_task:
                        print(f"\n  ✅ Агент: {agent['name']} | Задача: {active_task['title']}\n")
                    else:
                        print(f"\n  ✅ Агент: {agent['name']} | Создай задачу: /task new <название>\n")
                else:
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
                aname = ALL_AGENTS.get(ak, ALL_AGENTS["chat"])["name"]
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
                agent     = ALL_AGENTS.get(ak2, ALL_AGENTS["chat"])
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

            # Manager — используем pipeline runner
            active_task = get_active_task(session_id) if agent_key == "manager" else None

            if agent_key == "manager":
                if not active_task:
                    print("\n  ℹ️  Нет активной задачи. Создай: /task new <название>\n")
                    continue
                if active_task["is_paused"]:
                    print("\n  ⏸ Задача на паузе. Введи /task resume чтобы продолжить.\n")
                    continue
                # Пересоздаём runner если задача изменилась
                if not pipeline_runner or pipeline_runner.task["id"] != active_task["id"]:
                    pipeline_runner = PipelineRunner(active_task, profile_prompt, call_api)
                else:
                    pipeline_runner.task = active_task
                    pipeline_runner.profile_prompt = profile_prompt
                cur_agent = pipeline_runner.current_agent()
                print(f"  [{cur_agent['name']}] думаю...", end="\r")
                messages = pipeline_runner.build_messages(user_input)
            else:
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

            # Для Manager — сохраняем в task_messages
            if agent_key == "manager" and active_task:
                save_task_message(active_task["id"], active_task["state"], "user",      user_input)
                save_task_message(active_task["id"], active_task["state"], "assistant", answer)

            if agent_key == "manager" and active_task and pipeline_runner:
                cur_agent = pipeline_runner.current_agent()
                clean, action = pipeline_runner.handle_response(answer, active_task["id"])

                print(f"\n  {cur_agent['name']}:\n{clean}\n")
                print(format_token_line(usage, cur_agent["name"]))

                if action == "paused":
                    print(f"\n  ⚠️  Агент сомневается. Задача на паузе.")
                    print(f"  Проверь и введи /task resume чтобы продолжить.\n")

                elif action == "ready_confirm":
                    old_state = active_task["state"]
                    print(f"\n  🟢 {cur_agent['name']} завершил этап.")
                    yn = input("  Переходим к следующему агенту? [y/n]: ").strip().lower()
                    if yn == "y":
                        new_st = next_state(old_state)
                        update_task_state(active_task["id"], new_st)
                        active_task = get_active_task(session_id)
                        pipeline_runner.task = active_task
                        new_agent = PIPELINE_AGENTS.get(new_st, {}).get("name", new_st)
                        pipeline_runner.show_handoff(old_state, new_st)
                        print(f"  Теперь работает: {new_agent}\n")
                        if new_st == "done":
                            close_task(active_task["id"])
                    else:
                        print("  Остаёмся на текущем этапе.\n")

                elif action and action.startswith("auto_transition:"):
                    old_state = active_task["state"]
                    new_st    = action.split(":")[1]
                    active_task = get_active_task(session_id)
                    if active_task:
                        pipeline_runner.task = active_task
                    new_agent = PIPELINE_AGENTS.get(new_st, {}).get("name", new_st)
                    pipeline_runner.show_handoff(old_state, new_st)
                    print(f"  ⚡ Авто-передача: теперь работает {new_agent}\n")

                else:
                    state_meta = STATE_META[active_task["state"]]
                    print(f"  📍 {cur_agent['name']} | {state_meta['label']} | /task next — принудительный переход")
            else:
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
