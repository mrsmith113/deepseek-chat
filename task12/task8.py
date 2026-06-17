import os
import sqlite3
import requests
import threading
from datetime import datetime

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DB_FILE = "agent_memory.db"

MODEL_CONTEXT_LIMIT = 500      # искусственно занижен для теста (реальный: 64_000)   # токенов контекста у deepseek-chat
WARN_THRESHOLD      = 0.80     # предупреждаем при 80% заполнения

INPUT_PRICE  = 0.14  # $ за 1M токенов
OUTPUT_PRICE = 0.28

ROLES = {
    "1": {
        "name": "👶 Ребёнок (7 лет)",
        "system": (
            "Ты объясняешь всё как будто говоришь с семилетним ребёнком. "
            "Используй простые слова, короткие предложения, смешные и понятные примеры из жизни."
        ),
    },
    "2": {
        "name": "🎓 Студент",
        "system": (
            "Ты объясняешь как опытный старшекурсник своему однокурснику. "
            "Используй термины, но объясняй их. Давай примеры из учёбы и практики."
        ),
    },
    "3": {
        "name": "🧑‍🏫 Профессор",
        "system": (
            "Ты объясняешь как профессор с многолетним опытом. "
            "Строгая терминология, глубокий анализ. "
            "Структурированно: определение → суть → примеры → выводы."
        ),
    },
    "4": {
        "name": "🤖 Ассистент (без роли)",
        "system": "Ты полезный ассистент. Отвечай чётко и по делу.",
    },
}


# ───────────────────────────────────────────
# БД
# ───────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            role_key   TEXT DEFAULT '4',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER,
            role          TEXT,
            content       TEXT,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            created_at    TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    conn.commit()
    conn.close()

def create_session(name, role_key="4"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO sessions (name, role_key, created_at) VALUES (?, ?, ?)",
        (name, role_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def list_sessions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.role_key, s.created_at, COUNT(m.id)
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        GROUP BY s.id ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role_key FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    role_key = row[0] if row else "4"
    c.execute(
        "SELECT role, content, input_tokens, output_tokens FROM messages "
        "WHERE session_id=? ORDER BY id",
        (session_id,)
    )
    rows = c.fetchall()
    conn.close()
    messages = [{"role": r, "content": ct} for r, ct, _, _ in rows]
    token_log = [(r, ct, it, ot) for r, ct, it, ot in rows]
    return role_key, messages, token_log

def save_message(session_id, role, content, input_tokens=0, output_tokens=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (session_id, role, content, input_tokens, output_tokens, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, input_tokens, output_tokens,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def update_session_role(session_id, role_key):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE sessions SET role_key=? WHERE id=?", (role_key, session_id))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


# ───────────────────────────────────────────
# Агент
# ───────────────────────────────────────────

class Agent:
    def __init__(self, session_id, role_key, history, token_log):
        self.session_id          = session_id
        self.role_key            = role_key
        self.history             = history
        self.token_log           = token_log   # [(role, content, input_tok, output_tok)]
        self.total_input_tokens  = sum(r[2] for r in token_log)
        self.total_output_tokens = sum(r[3] for r in token_log)
        self.request_count       = sum(1 for r in token_log if r[0] == "assistant")

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key
        update_session_role(self.session_id, key)

    def reset(self):
        self.history             = []
        self.token_log           = []
        self.total_input_tokens  = 0
        self.total_output_tokens = 0
        self.request_count       = 0
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM messages WHERE session_id=?", (self.session_id,))
        conn.commit()
        conn.close()

    def history_tokens(self):
        """Грубая оценка токенов истории: ~4 символа = 1 токен"""
        total_chars = sum(len(m["content"]) for m in self.history)
        return total_chars // 4

    def context_usage_pct(self):
        return self.history_tokens() / MODEL_CONTEXT_LIMIT * 100

    def stats(self):
        cost = (self.total_input_tokens  / 1_000_000 * INPUT_PRICE +
                self.total_output_tokens / 1_000_000 * OUTPUT_PRICE)
        return {
            "requests":      self.request_count,
            "input_tokens":  self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens":  self.total_input_tokens + self.total_output_tokens,
            "history_est":   self.history_tokens(),
            "context_pct":   self.context_usage_pct(),
            "cost":          cost,
        }

    def run(self, user_input):
        self.history.append({"role": "user", "content": user_input})
        save_message(self.session_id, "user", user_input)

        # Обрезаем историю если превышен лимит (4 символа ~ 1 токен)
        trimmed = self.history[:]
        while sum(len(m["content"]) for m in trimmed) // 4 > MODEL_CONTEXT_LIMIT and len(trimmed) > 1:
            trimmed.pop(0)
            if trimmed and trimmed[0]["role"] == "assistant":
                trimmed.pop(0)
        if len(trimmed) < len(self.history):
            removed = len(self.history) - len(trimmed)
            self.history = trimmed   # обновляем историю — бар откатится
            print(f"  ✂️  История обрезана: удалено {removed} старых сообщений, контекст освобождён")
        messages = [{"role": "system", "content": self.role["system"]}] + self.history

        result     = {}
        done_event = threading.Event()

        def do_request():
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": "deepseek-chat", "messages": messages},
            )
            data = response.json()
            if "choices" in data:
                result["answer"] = data["choices"][0]["message"]["content"]
                result["usage"]  = data.get("usage", {})
                result["error"]  = None
            else:
                result["answer"] = None
                result["error"]  = data.get("error", {})
            done_event.set()

        thread = threading.Thread(target=do_request)
        thread.start()
        if not done_event.wait(timeout=3):
            print("Ну и задачка, всё ещё думаю :)")
        thread.join()

        if result["error"]:
            err = result["error"]
            print(f"\n❌ Ошибка API: {err.get('message', err)}")
            print(f"   Код: {err.get('code', '?')}")
            if "context" in str(err).lower() or "length" in str(err).lower():
                print(f"   ⚠️  Вероятно превышен лимит контекста ({MODEL_CONTEXT_LIMIT:,} токенов)")
                print(f"   Используй /reset чтобы очистить историю.")
            self.history.pop()  # убираем незавершённый user message
            return None

        answer       = result["answer"]
        usage        = result.get("usage", {})
        input_tok    = usage.get("prompt_tokens", 0)
        output_tok   = usage.get("completion_tokens", 0)

        self.history.append({"role": "assistant", "content": answer})
        save_message(self.session_id, "assistant", answer, input_tok, output_tok)

        self.token_log.append(("user",      user_input, 0,         0))
        self.token_log.append(("assistant", answer,     input_tok, output_tok))
        self.total_input_tokens  += input_tok
        self.total_output_tokens += output_tok
        self.request_count       += 1

        return answer, input_tok, output_tok


# ───────────────────────────────────────────
# Вывод токен-строки после каждого ответа
# ───────────────────────────────────────────

def print_token_line(input_tok, output_tok, agent):
    s           = agent.stats()
    cost_req    = (input_tok  / 1_000_000 * INPUT_PRICE +
                   output_tok / 1_000_000 * OUTPUT_PRICE)
    pct         = s["context_pct"]
    bar_filled  = int(pct / 5)       # 20 делений
    bar         = "█" * bar_filled + "░" * (20 - bar_filled)

    warn = ""
    if pct >= WARN_THRESHOLD * 100:
        warn = "  ⚠️  БЛИЗКО К ЛИМИТУ!"
    elif pct >= 50:
        warn = "  🟡"

    print(
        f"  📊 запрос: {input_tok} | ответ: {output_tok} | "
        f"история ~{s['history_est']:,} tok | "
        f"итого: {s['total_tokens']:,} tok | "
        f"сессия: ${s['cost']:.6f}"
    )
    print(f"  🧠 контекст: [{bar}] {pct:.1f}% / 100%{warn}")


# ───────────────────────────────────────────
# Таблица роста токенов /tokens
# ───────────────────────────────────────────

def show_token_table(agent):
    divider("РОСТ ТОКЕНОВ ПО ДИАЛОГУ")
    if not agent.token_log:
        print("  Нет данных.\n")
        return

    accumulated = 0
    print(f"  {'#':<4} {'Роль':<10} {'Символов':<10} {'output_tok':<12} {'Накоплено output'}")
    print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*12} {'-'*16}")
    for i, (role, content, in_tok, out_tok) in enumerate(agent.token_log, 1):
        accumulated += out_tok
        role_label = "Ты" if role == "user" else "Агент"
        print(f"  {i:<4} {role_label:<10} {len(content):<10} {out_tok:<12} {accumulated}")

    s = agent.stats()
    print(f"\n  Итого input:  {s['input_tokens']:,} токенов")
    print(f"  Итого output: {s['output_tokens']:,} токенов")
    print(f"  Стоимость:    ${s['cost']:.6f}")
    print(f"  Контекст:     ~{s['history_est']:,} / {MODEL_CONTEXT_LIMIT:,} токенов ({s['context_pct']:.1f}%)\n")


# ───────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def show_help():
    print("""
Команды:
  /role     — сменить роль агента
  /reset    — сбросить память текущей сессии
  /history  — показать историю диалога
  /stats    — токены и стоимость (сводка)
  /tokens   — таблица роста токенов по диалогу
  /sessions — список всех сессий
  /exit     — выход
""")

def show_roles():
    print("\nВыбери роль:")
    for k, r in ROLES.items():
        print(f"  [{k}] {r['name']}")

def choose_or_create_session():
    sessions = list_sessions()
    if not sessions:
        print("\nСессий нет. Создаём новую.")
        name = input("Название сессии (Enter = 'Сессия 1'): ").strip() or "Сессия 1"
        sid = create_session(name)
        return sid, "4", [], []

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<20} {'Роль':<22} {'Создана':<20} {'Сообщ.'}")
    print(f"  {'-'*4} {'-'*20} {'-'*22} {'-'*20} {'-'*6}")
    for sid, name, rk, created_at, msg_count in sessions:
        rname = ROLES.get(rk, ROLES["4"])["name"]
        print(f"  {sid:<4} {name:<20} {rname:<22} {created_at:<20} {msg_count}")

    print("\n  [N] Новая сессия   [D] Удалить сессию")
    valid_ids = [str(s[0]) for s in sessions]

    while True:
        choice = input("\nВыбери ID или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("Название: ").strip() or f"Сессия {len(sessions)+1}"
            sid = create_session(name)
            return sid, "4", [], []
        elif choice == "D":
            did = input("ID для удаления: ").strip()
            if did in valid_ids:
                delete_session(int(did))
                print(f"✅ Сессия {did} удалена.")
                return choose_or_create_session()
        elif choice in valid_ids:
            sid = int(choice)
            rk, history, token_log = load_session(sid)
            return sid, rk, history, token_log
        else:
            print("Неверный выбор.")


# ───────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────

init_db()
divider("ЗАДАНИЕ 8 — Агент с подсчётом токенов")

session_id, role_key, history, token_log = choose_or_create_session()
agent = Agent(session_id, role_key, history, token_log)

if history:
    s = agent.stats()
    print(f"\n✅ Сессия загружена. Сообщений: {len(history)} | "
          f"Токенов накоплено: {s['total_tokens']:,} | "
          f"Контекст: {s['context_pct']:.1f}%")
    print(f"   Роль: {agent.role['name']}\n")
else:
    print(f"\n✅ Новая сессия. Роль: {agent.role['name']}")
    print("   Введи /help для справки.\n")

while True:
    try:
        user_input = input("Ты: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nВыход.")
        break

    if not user_input:
        continue

    elif user_input == "/exit":
        print("\nПока! История сохранена.\n")
        break

    elif user_input == "/help":
        show_help()

    elif user_input == "/role":
        show_roles()
        while True:
            choice = input("Твой выбор [1-4]: ").strip()
            if choice in ROLES:
                agent.set_role(choice)
                print(f"\n✅ Роль: {agent.role['name']}\n")
                break
            print("Введи 1-4")

    elif user_input == "/reset":
        agent.reset()
        print("🗑️  Память сброшена.\n")

    elif user_input == "/history":
        if not agent.history:
            print("\n  История пуста.\n")
        else:
            divider("ИСТОРИЯ")
            for msg in agent.history:
                label = "Ты" if msg["role"] == "user" else f"Агент ({agent.role['name']})"
                print(f"\n[{label}]\n{msg['content']}")
            print()

    elif user_input == "/stats":
        s = agent.stats()
        divider("СТАТИСТИКА")
        print(f"  Запросов       : {s['requests']}")
        print(f"  Input токены   : {s['input_tokens']:,}")
        print(f"  Output токены  : {s['output_tokens']:,}")
        print(f"  Всего токенов  : {s['total_tokens']:,}")
        print(f"  История ~      : {s['history_est']:,} tok")
        print(f"  Контекст       : {s['context_pct']:.1f}% от {MODEL_CONTEXT_LIMIT:,}")
        print(f"  Стоимость      : ${s['cost']:.6f}")
        print(f"  Роль           : {agent.role['name']}\n")

    elif user_input == "/tokens":
        show_token_table(agent)

    elif user_input == "/sessions":
        sessions = list_sessions()
        divider("ВСЕ СЕССИИ")
        for sid, name, rk, created_at, msg_count in sessions:
            mark = " ◀ текущая" if sid == agent.session_id else ""
            print(f"  [{sid}] {name} | {ROLES.get(rk, ROLES['4'])['name']} | "
                  f"{msg_count} сообщ. | {created_at}{mark}")
        print()

    else:
        result = agent.run(user_input)
        if result:
            answer, input_tok, output_tok = result
            print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
            print_token_line(input_tok, output_tok, agent)
            print()
