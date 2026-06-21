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
                # Авто-переход
                new_state = next_state(state)
                if new_state != state:
                    update_task_state(task_id, new_state)
                    self.task = get_active_task(self.task["session_id"] if "session_id" in self.task else task_id)
                    if new_state == "done":
                        close_task(task_id)
                return text, f"auto_transition:{new_state}"

        return text, None

    def force_transition(self, task_id):
        """Принудительный переход (по /task next)"""
        state     = self.task["state"]
        text_history = load_task_history(task_id)
        # Сохраняем последний ответ как артефакт
        for msg in reversed(text_history):
            if msg["role"] == "assistant":
                save_artifact(task_id, state, clean_answer(msg["content"]))
                break

        new_state = next_state(state)
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
