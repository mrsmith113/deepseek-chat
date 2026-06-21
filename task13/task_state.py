"""
Task State Machine для агента Manager.
Этапы: planning → execution → validation → done
"""

import sqlite3
import json
from datetime import datetime

DB_FILE = "hornest.db"

STATES = ["planning", "execution", "validation", "done"]

STATE_META = {
    "planning": {
        "label":    "🗓 Планирование",
        "prompt":   (
            "Ты ведёшь задачу на этапе ПЛАНИРОВАНИЯ. "
            "Уточни цель, декомпозируй на шаги, зафиксируй план. "
            "Задавай уточняющие вопросы. "
            "Когда план полностью готов — добавь в конец ответа строку: [READY]"
        ),
        "expected": "Уточни цель и составь план шагов",
    },
    "execution": {
        "label":    "⚙️ Выполнение",
        "prompt":   (
            "Ты ведёшь задачу на этапе ВЫПОЛНЕНИЯ. "
            "Веди по шагам плана один за другим. "
            "После каждого шага фиксируй результат. "
            "Когда ВСЕ шаги выполнены — добавь в конец ответа строку: [READY]"
        ),
        "expected": "Выполняй шаги плана по очереди",
    },
    "validation": {
        "label":    "✅ Проверка",
        "prompt":   (
            "Ты ведёшь задачу на этапе ВАЛИДАЦИИ. "
            "Проверь результаты: всё ли сделано, нет ли ошибок. "
            "Если сомневаешься в результате — добавь: [PAUSE] "
            "Если всё ок — добавь в конец ответа строку: [READY]"
        ),
        "expected": "Проверь результаты и выяви проблемы",
    },
    "done": {
        "label":    "🏁 Завершено",
        "prompt":   (
            "Задача завершена. "
            "Подведи итог: что сделано, какие результаты, что улучшить."
        ),
        "expected": "Задача выполнена",
    },
}

AGENT_SIGNALS = {
    "[READY]": "готов к переходу на следующий этап",
    "[PAUSE]": "сомневается, нужна проверка пользователем",
}


def get_conn():
    return sqlite3.connect(DB_FILE, timeout=10)


def init_task_tables():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER,
            title       TEXT,
            state       TEXT DEFAULT 'planning',
            step        INTEGER DEFAULT 0,
            is_active   INTEGER DEFAULT 1,
            is_paused             INTEGER DEFAULT 0,
            confirm_transitions   INTEGER DEFAULT 0,
            context               TEXT DEFAULT '{}',
            created_at  TEXT,
            updated_at  TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS task_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id    INTEGER,
            state      TEXT,
            role       TEXT,
            content    TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────

def create_task(session_id, title, confirm=False):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE tasks SET is_active=0 WHERE session_id=?", (session_id,))
    c.execute("INSERT INTO tasks (session_id,title,state,step,is_active,is_paused,confirm_transitions,context,created_at,updated_at) "
              "VALUES (?,?,'planning',0,1,0,?,'{}',?,?)",
              (session_id, title, 1 if confirm else 0, now, now))
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_active_task(session_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, state, step, is_paused, confirm_transitions, context "
              "FROM tasks WHERE session_id=? AND is_active=1 LIMIT 1",
              (session_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id":                  row[0],
            "title":               row[1],
            "state":               row[2],
            "step":                row[3],
            "is_paused":           row[4],
            "confirm_transitions": row[5],
            "context":             json.loads(row[6]),
        }
    return None


def list_tasks(session_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, title, state, is_active, is_paused, created_at "
              "FROM tasks WHERE session_id=? ORDER BY id DESC",
              (session_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_task_state(task_id, state, step=None):
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if step is not None:
        conn.execute("UPDATE tasks SET state=?, step=?, updated_at=? WHERE id=?",
                     (state, step, now, task_id))
    else:
        conn.execute("UPDATE tasks SET state=?, updated_at=? WHERE id=?",
                     (state, now, task_id))
    conn.commit()
    conn.close()


def pause_task(task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET is_paused=1, updated_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
    conn.commit()
    conn.close()


def resume_task(task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET is_paused=0, updated_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
    conn.commit()
    conn.close()


def close_task(task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET is_active=0, updated_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
    conn.commit()
    conn.close()


def resume_task_by_id(session_id, task_id):
    conn = get_conn()
    conn.execute("UPDATE tasks SET is_active=0 WHERE session_id=?", (session_id,))
    conn.execute("UPDATE tasks SET is_active=1, is_paused=0, updated_at=? WHERE id=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
    conn.commit()
    conn.close()


def save_task_message(task_id, state, role, content):
    conn = get_conn()
    conn.execute("INSERT INTO task_messages (task_id,state,role,content,created_at) VALUES (?,?,?,?,?)",
                 (task_id, state, role, content,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def load_task_history(task_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT role, content FROM task_messages WHERE task_id=? ORDER BY id",
              (task_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "content": ct} for r, ct in rows]


# ── State transitions ─────────────────────

def next_state(current_state):
    idx = STATES.index(current_state)
    if idx < len(STATES) - 1:
        return STATES[idx + 1]
    return current_state


def build_task_messages(task, agent_system, profile_prompt, user_input):
    """Контекст для запроса с учётом этапа задачи"""
    state_meta = STATE_META[task["state"]]
    msgs = [
        {"role": "system", "content": agent_system},
    ]
    if profile_prompt:
        msgs.append({"role": "system", "content": profile_prompt})

    msgs.append({"role": "system", "content": (
        f"🗂 АКТИВНАЯ ЗАДАЧА: {task['title']}\n"
        f"Этап: {state_meta['label']} ({STATES.index(task['state'])+1}/{len(STATES)})\n"
        f"Ожидается: {state_meta['expected']}\n\n"
        f"{state_meta['prompt']}"
    )})

    # история задачи
    history = load_task_history(task["id"])
    msgs += history
    msgs.append({"role": "user", "content": user_input})
    return msgs


# ── Display ───────────────────────────────

def show_task_status(task):
    state_meta = STATE_META[task["state"]]
    idx        = STATES.index(task["state"])

    print(f"\n  {'─'*50}")
    print(f"  🗂 Задача: {task['title']}")
    print(f"  {'─'*50}")

    # прогресс-бар
    bar = ""
    for i, s in enumerate(STATES):
        meta = STATE_META[s]
        if i < idx:
            bar += f"  ✅ {meta['label']}"
        elif i == idx:
            bar += f"  ▶️  {meta['label']}  ← сейчас"
        else:
            bar += f"  ⬜ {meta['label']}"
        if i < len(STATES)-1:
            bar += " →\n"
    print(bar)

    paused = "  ⏸ ПАУЗА" if task["is_paused"] else ""
    print(f"\n  Ожидается: {state_meta['expected']}{paused}")
    print(f"  {'─'*50}\n")


# ── Сигналы агента ────────────────────────

def detect_signal(answer):
    """Ловим [READY] или [PAUSE] в ответе агента"""
    if "[READY]" in answer:
        return "ready"
    if "[PAUSE]" in answer:
        return "pause"
    return None


def clean_answer(answer):
    """Убираем служебные маркеры из ответа перед показом"""
    return answer.replace("[READY]", "").replace("[PAUSE]", "").strip()


# ── Параллельные субагенты ────────────────

def run_parallel_subagents(subagents, context, call_api_fn):
    """
    Запускает нескольких субагентов параллельно.

    subagents: [{"name": "Юрист", "system": "...", "question": "..."}]
    context: список сообщений (история задачи)
    call_api_fn: функция вызова API

    Возвращает список результатов в том же порядке.
    """
    import threading

    results = [None] * len(subagents)

    def run_one(i, sub):
        msgs = [{"role": "system", "content": sub["system"]}]
        msgs += context
        msgs.append({"role": "user", "content": sub["question"]})
        r = call_api_fn(msgs)
        results[i] = {
            "name":   sub["name"],
            "answer": r.get("answer") or "❌ Ошибка",
            "usage":  r.get("usage", {}),
        }

    threads = [threading.Thread(target=run_one, args=(i, sub))
               for i, sub in enumerate(subagents)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


def merge_subagent_results(results):
    """Сливает результаты субагентов в один блок для оркестратора"""
    parts = []
    for r in results:
        parts.append(f"=== {r['name']} ===\n{r['answer']}")
    return "\n\n".join(parts)


def demo_parallel(task, call_api_fn):
    """
    Демо параллельных субагентов на этапе execution.
    В реальном проекте subagents настраиваются под конкретную задачу.
    """
    history = load_task_history(task["id"])

    subagents = [
        {
            "name":     "🔍 Аналитик",
            "system":   "Ты аналитик. Анализируй задачу с точки зрения рисков и возможностей.",
            "question": f"Задача: {task['title']}. Дай краткий анализ рисков (3-5 пунктов).",
        },
        {
            "name":     "🛠 Исполнитель",
            "system":   "Ты исполнитель. Предлагай конкретные шаги реализации.",
            "question": f"Задача: {task['title']}. Предложи 3-5 конкретных шага реализации.",
        },
    ]

    print("\n  🔄 Запускаю параллельных субагентов...")
    print(f"  {'─'*50}")

    results = run_parallel_subagents(subagents, history, call_api_fn)

    for r in results:
        tok = r["usage"].get("prompt_tokens", 0)
        print(f"\n  {r['name']} ({tok} tok):")
        print(f"  {r['answer'][:300]}{'...' if len(r['answer'])>300 else ''}")

    merged = merge_subagent_results(results)
    print(f"\n  {'─'*50}")
    print(f"  ✅ Результаты субагентов собраны. Передаю оркестратору...\n")
    return merged
