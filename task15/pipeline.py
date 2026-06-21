"""
Pipeline — рой агентов.
Каждый этап задачи — отдельный специализированный агент.
Агент получает артефакт предыдущего и передаёт свой следующему.

Planner → Executor → Validator → Summarizer
"""

import json
import threading
from datetime import datetime
from task_state import (STATES, STATE_META, detect_signal, clean_answer,
                        load_task_history, save_task_message,
                        update_task_state, next_state, close_task,
                        get_active_task, pause_task)
from guard import run_guard, show_guard_result

# ── Агенты пайплайна ──────────────────────

PIPELINE_AGENTS = {
    "planning": {
        "name":   "🗓 Planner",
        "system": (
            "Ты Planner — агент планирования. Твоя единственная задача: "
            "получить описание задачи от пользователя, задать уточняющие вопросы "
            "и создать структурированный план выполнения. "
            "Когда план готов — выведи его в формате:\n"
            "ПЛАН:\n1. шаг\n2. шаг\n...\n"
            "и добавь в конец: [READY]\n"
            "Не выполняй задачу сам — только планируй."
        ),
    },
    "execution": {
        "name":   "⚙️ Executor",
        "system": (
            "Ты Executor — агент выполнения. Ты получаешь готовый план от Planner "
            "и выполняешь его шаг за шагом. "
            "После каждого шага спрашивай пользователя: всё ок, продолжаем? "
            "Когда все шаги выполнены — выведи:\n"
            "РЕЗУЛЬТАТ:\n[краткое описание что сделано]\n"
            "и добавь в конец: [READY]\n"
            "Не придумывай новые шаги — работай строго по плану."
        ),
    },
    "validation": {
        "name":   "✅ Validator",
        "system": (
            "Ты Validator — агент проверки. Ты получаешь план и результат выполнения. "
            "Проверяй: все ли шаги выполнены, нет ли ошибок, соответствует ли результат плану. "
            "Если сомневаешься — добавь [PAUSE] и объясни проблему. "
            "Если всё ок — выведи:\n"
            "ЗАКЛЮЧЕНИЕ: [ок/не ок]\nПРОБЛЕМЫ: [список или 'нет']\n"
            "и добавь в конец: [READY]"
        ),
    },
    "done": {
        "name":   "🏁 Summarizer",
        "system": (
            "Ты Summarizer — агент подведения итогов. "
            "Ты получаешь весь артефакт задачи: план, результат, заключение валидатора. "
            "Подведи финальный итог: что было сделано, какой результат, "
            "что можно улучшить в следующий раз. "
            "Оформи красиво и структурированно."
        ),
    },
}


# ── Артефакты ─────────────────────────────

def save_artifact(task_id, stage, content):
    """Сохраняем артефакт этапа как системное сообщение"""
    from db import get_conn
    conn = get_conn()
    conn.execute(
        "INSERT INTO task_messages (task_id,state,role,content,created_at) VALUES (?,?,?,?,?)",
        (task_id, stage, "artifact",
         f"[ARTIFACT:{stage.upper()}]\n{content}",
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def load_artifacts(task_id):
    """Загружаем все артефакты задачи"""
    from db import get_conn
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT state, content FROM task_messages "
              "WHERE task_id=? AND role='artifact' ORDER BY id",
              (task_id,))
    rows = c.fetchall()
    conn.close()
    return {state: content for state, content in rows}


def build_artifact_context(task_id, current_stage):
    """
    Строим контекст для текущего агента:
    артефакты всех предыдущих этапов + rework заметки + история текущего этапа
    """
    from db import get_conn
    artifacts   = load_artifacts(task_id)
    stage_order = ["planning", "execution", "validation"]
    current_idx = stage_order.index(current_stage) if current_stage in stage_order else 0

    # Артефакты предыдущих этапов
    artifact_msgs = []
    for stage in stage_order[:current_idx]:
        if stage in artifacts:
            artifact_msgs.append({
                "role":    "system",
                "content": f"📋 Артефакт этапа [{stage.upper()}]:\n{artifacts[stage]}"
            })

    # Rework артефакт — если был откат на этот этап
    rework_key = f"{current_stage}_rework"
    if rework_key in artifacts:
        artifact_msgs.append({
            "role":    "system",
            "content": f"⚠️ ЗАПРОС НА ДОРАБОТКУ от пользователя:\n{artifacts[rework_key]}\n\nУчти этот комментарий и переработай результат."
        })

    # История сообщений текущего этапа (user + assistant)
    history = load_task_history(task_id)
    current_history = [m for m in history if m["role"] in ("user", "assistant")]

    return artifact_msgs, current_history


# ── Pipeline runner ───────────────────────

class PipelineRunner:
    def __init__(self, task, profile_prompt, call_api_fn):
        self.task          = task
        self.profile_prompt = profile_prompt
        self.call_api      = call_api_fn
        self.confirm       = bool(task.get("confirm_transitions", 0))

    def current_agent(self):
        state = self.task["state"]
        return PIPELINE_AGENTS.get(state, PIPELINE_AGENTS["planning"])

    def build_messages(self, user_input):
        agent      = self.current_agent()
        state      = self.task["state"]
        state_meta = STATE_META[state]

        artifact_msgs, current_history = build_artifact_context(
            self.task["id"], state
        )

        msgs = [{"role": "system", "content": agent["system"]}]

        if self.profile_prompt:
            msgs.append({"role": "system", "content": self.profile_prompt})

        msgs.append({"role": "system", "content": (
            f"🗂 Задача: {self.task['title']}\n"
            f"Твой этап: {state_meta['label']} "
            f"({STATES.index(state)+1}/{len(STATES)})"
        )})

        # артефакты предыдущих агентов
        msgs += artifact_msgs

        # история текущего агента
        msgs += current_history
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def handle_response(self, answer, task_id):
        """
        Обрабатываем ответ: ловим сигналы, управляем переходами.
        Возвращает (clean_text, action)
        action: None | "transitioned" | "paused"
        """
        signal = detect_signal(answer)
        text   = clean_answer(answer)
        state  = self.task["state"]

        if signal == "pause":
            pause_task(task_id)
            return text, "paused"

        if signal == "ready":
            # Сохраняем артефакт текущего этапа
            save_artifact(task_id, state, text)

            if self.confirm:
                return text, "ready_confirm"
            else:
                # ⛔ Guard проверяет артефакт перед переходом
                new_state = next_state(state)
                if new_state != state:
                    guard_result, guard_reason = run_guard(
                        text, self.task["title"], self.call_api
                    )
                    show_guard_result(guard_result, guard_reason, state, new_state)

                    if guard_result == "block":
                        # Автоматический rework — откат на текущий этап
                        _do_rework(task_id, state, f"[InvariantGuard]\n{guard_reason}")
                        self.task = get_active_task(
                            self.task.get("session_id", task_id)
                        )
                        return text, f"guard_block:{state}"

                    update_task_state(task_id, new_state)
                    self.task = get_active_task(
                        self.task.get("session_id", task_id)
                    )
                    if new_state == "done":
                        close_task(task_id)
                return text, f"auto_transition:{new_state}"

        return text, None

    def force_transition(self, task_id):
        """Принудительный переход (по /task next) — с проверкой Guard"""
        state        = self.task["state"]
        text_history = load_task_history(task_id)

        # ── Фильтруем только сообщения ТЕКУЩЕГО этапа ──
        current_msgs = [
            m for m in text_history
            if m.get("state") == state and m["role"] in ("user", "assistant")
        ]

        # ── Проверка 1: этап не начат? ──
        if not current_msgs:
            print(f"\n  ⛔ Нельзя перейти дальше — этап не начат.")
            print(f"  Сначала поговори с агентом {self.current_agent()['name']}.\n")
            return state

        # ── Проверка 2: Guard проверяет последний ответ текущего этапа ──
        last_answer = ""
        for msg in reversed(current_msgs):
            if msg["role"] == "assistant":
                last_answer = clean_answer(msg["content"])
                break

        new_state = next_state(state)
        if new_state != state and last_answer:
            guard_result, guard_reason = run_guard(
                last_answer, self.task["title"], self.call_api
            )
            show_guard_result(guard_result, guard_reason, state, new_state)

            if guard_result == "block":
                _do_rework(task_id, state, f"[InvariantGuard]\n{guard_reason}")
                self.task = get_active_task(self.task.get("session_id", task_id))
                return state  # остаёмся, откат сделан

        # ── Всё ок: сохраняем артефакт и переходим ──
        if last_answer:
            save_artifact(task_id, state, last_answer)

        update_task_state(task_id, new_state)
        if new_state == "done":
            close_task(task_id)
        return new_state

    def show_handoff(self, from_state, to_state):
        """Красивый вывод передачи управления"""
        from_agent = PIPELINE_AGENTS.get(from_state, {}).get("name", from_state)
        to_agent   = PIPELINE_AGENTS.get(to_state,   {}).get("name", to_state)
        print(f"\n  {'─'*50}")
        print(f"  🔄 Передача: {from_agent} → {to_agent}")
        print(f"  {'─'*50}\n")


# ── Параллельные субагенты пайплайна ──────

def run_pipeline_parallel(task, stage_subagents, call_api_fn):
    """
    Запускает нескольких субагентов параллельно внутри одного этапа.
    Результаты сливаются и передаются следующему агенту в пайплайне.

    stage_subagents: [{"name": "...", "system": "...", "question": "..."}]
    """
    artifacts = load_artifacts(task["id"])
    # Контекст — все предыдущие артефакты
    context = [
        {"role": "system", "content": f"📋 {state.upper()}:\n{content}"}
        for state, content in artifacts.items()
    ]

    results  = [None] * len(stage_subagents)
    done_evt = threading.Event()
    lock     = threading.Lock()
    finished = [0]

    def run_one(i, sub):
        msgs = [{"role": "system", "content": sub["system"]}]
        msgs += context
        msgs.append({"role": "user", "content": sub["question"]})
        r = call_api_fn(msgs)
        with lock:
            results[i] = {
                "name":   sub["name"],
                "answer": r.get("answer") or "❌ Ошибка",
                "usage":  r.get("usage", {}),
            }
            finished[0] += 1
            if finished[0] == len(stage_subagents):
                done_evt.set()

    threads = [threading.Thread(target=run_one, args=(i, sub))
               for i, sub in enumerate(stage_subagents)]
    for t in threads:
        t.start()

    # Показываем прогресс пока ждём
    print(f"  🔄 Параллельный запуск {len(threads)} субагентов...", end="", flush=True)
    while not done_evt.wait(timeout=1):
        print(".", end="", flush=True)
    print(" готово!\n")

    for t in threads:
        t.join()

    return results


def show_parallel_results(results):
    """Вывод результатов параллельных субагентов"""
    print(f"\n  {'─'*50}")
    for r in results:
        tok = r["usage"].get("prompt_tokens", 0)
        print(f"\n  {r['name']} ({tok} tok):")
        print(f"  {r['answer'][:400]}{'...' if len(r['answer'])>400 else ''}")
    print(f"\n  {'─'*50}\n")


def merge_for_orchestrator(task_title, results):
    """Готовим сводный запрос для следующего агента"""
    parts = [f"Задача: {task_title}\n"]
    for r in results:
        parts.append(f"--- {r['name']} ---\n{r['answer']}")
    return "\n\n".join(parts)


# ── Вспомогательная: автоматический rework ────────────────

def _do_rework(task_id, target_state, comment):
    """
    Автоматически откатывает этап с комментарием.
    Используется Guard-ом при блокировке перехода.
    """
    from db import get_conn
    # Очищаем историю этапа
    conn = get_conn()
    conn.execute(
        "DELETE FROM task_messages WHERE task_id=? AND state=? AND role IN ('user','assistant')",
        (task_id, target_state)
    )
    conn.commit()
    conn.close()
    # Сохраняем rework-комментарий как артефакт
    save_artifact(task_id, f"{target_state}_rework", comment)
    # Возвращаем state
    update_task_state(task_id, target_state)


# ── Рой агентов на этапе Planning ────────────────────────

SWARM_AGENTS = [
    {
        "name":   "🧠 Analyst",
        "system": (
            "Ты Analyst — агент анализа задачи. "
            "Твоя задача: разобрать запрос пользователя, выявить скрытые требования, "
            "риски и неоднозначности. Не предлагай решение — только анализируй. "
            "Будь краток: 3-5 ключевых наблюдений."
        ),
    },
    {
        "name":   "🏗 Architect",
        "system": (
            "Ты Architect — агент проектирования. "
            "Твоя задача: предложить структуру решения — модули, компоненты, подходы. "
            "Не пиши код — только архитектуру. "
            "Будь краток: опиши структуру в 3-5 пунктах."
        ),
    },
    {
        "name":   "🔍 Researcher",
        "system": (
            "Ты Researcher — агент исследования. "
            "Твоя задача: найти подводные камни, альтернативные подходы, "
            "что может пойти не так. Думай критически. "
            "Будь краток: 3-5 замечаний."
        ),
    },
]


def run_swarm_planning(task, call_api_fn):
    """
    Рой из 3 агентов параллельно анализирует задачу на этапе Planning.
    Возвращает список результатов.
    """
    question = f"Задача для анализа: {task['title']}"
    subagents = [
        {**agent, "question": question}
        for agent in SWARM_AGENTS
    ]
    print(f"\n  🐝 Запускаю рой агентов для анализа задачи...")
    results = run_pipeline_parallel(task, subagents, call_api_fn)
    return results


def swarm_then_orchestrate(task, call_api_fn):
    """
    Полный цикл роя на Planning:
    1. 3 агента параллельно анализируют задачу
    2. Показываем результаты
    3. Orchestrator делает сводный план
    4. Guard проверяет план на инварианты
    
    Возвращает (plan_text, guard_result, guard_reason)
    """
    # Шаг 1: рой
    results = run_swarm_planning(task, call_api_fn)
    show_parallel_results(results)

    # Шаг 2: оркестратор
    merged = merge_for_orchestrator(task["title"], results)
    orch_system = PIPELINE_AGENTS["planning"]["system"]

    print(f"  🎯 Orchestrator формирует план...\n")
    orch_msgs = [
        {"role": "system", "content": orch_system},
        {"role": "system", "content": (
            f"🗂 Задача: {task['title']}\n"
            f"Ты получил анализ от трёх агентов. "
            f"На основе их мнений составь финальный структурированный план."
        )},
        {"role": "user", "content": (
            f"Вот анализ от команды агентов:\n\n{merged}\n\n"
            f"Составь финальный ПЛАН выполнения задачи. "
            f"Формат:\nПЛАН:\n1. шаг\n2. шаг\n...\n\n"
            f"В конце добавь [READY]"
        )}
    ]

    r = call_api_fn(orch_msgs)
    plan_text = clean_answer(r.get("answer", ""))

    # Шаг 3: Guard
    print(f"  ⛔ InvariantGuard проверяет план...\n")
    guard_result, guard_reason = run_guard(plan_text, task["title"], call_api_fn)

    return plan_text, guard_result, guard_reason
