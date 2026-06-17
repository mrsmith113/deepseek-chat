import os
import sqlite3
import requests
import threading
from datetime import datetime

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DB_FILE = "agent_memory.db"

ROLES = {
    "1": {
        "name": "👶 Ребёнок (7 лет)",
        "system": (
            "Ты объясняешь всё как будто говоришь с семилетним ребёнком. "
            "Используй простые слова, короткие предложения, смешные и понятные примеры из жизни. "
            "Никаких сложных терминов — только то, что поймёт первоклассник."
        ),
    },
    "2": {
        "name": "🎓 Студент",
        "system": (
            "Ты объясняешь как опытный старшекурсник своему однокурснику. "
            "Используй термины, но объясняй их. Давай примеры из учёбы и практики. "
            "Можно немного неформально, но по делу."
        ),
    },
    "3": {
        "name": "🧑‍🏫 Профессор",
        "system": (
            "Ты объясняешь как профессор с многолетним опытом. "
            "Строгая терминология, глубокий анализ, ссылки на теорию. "
            "Структурированно: определение → суть → примеры → выводы."
        ),
    },
    "4": {
        "name": "🤖 Ассистент (без роли)",
        "system": "Ты полезный ассистент. Отвечай чётко и по делу.",
    },
}


# ───────────────────────────────────────────
# База данных
# ───────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT,
            role_key  TEXT DEFAULT '4',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            role       TEXT,
            content    TEXT,
            created_at TEXT,
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
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id

def list_sessions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.role_key, s.created_at,
               COUNT(m.id) as msg_count
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role_key FROM sessions WHERE id = ?", (session_id,))
    row = c.fetchone()
    role_key = row[0] if row else "4"
    c.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,)
    )
    messages = [{"role": r, "content": ct} for r, ct in c.fetchall()]
    conn.close()
    return role_key, messages

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def update_session_role(session_id, role_key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE sessions SET role_key = ? WHERE id = ?", (role_key, session_id))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# ───────────────────────────────────────────
# Агент
# ───────────────────────────────────────────

class Agent:
    def __init__(self, session_id, role_key, history):
        self.session_id          = session_id
        self.role_key            = role_key
        self.history             = history
        self.total_input_tokens  = 0
        self.total_output_tokens = 0
        self.request_count       = 0

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key
        update_session_role(self.session_id, key)

    def reset(self):
        self.history = []
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
        conn.commit()
        conn.close()

    def stats(self):
        cost = (self.total_input_tokens  / 1_000_000 * 0.14 +
                self.total_output_tokens / 1_000_000 * 0.28)
        return {
            "requests":      self.request_count,
            "input_tokens":  self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens":  self.total_input_tokens + self.total_output_tokens,
            "cost":          cost,
        }

    def run(self, user_input):
        self.history.append({"role": "user", "content": user_input})
        save_message(self.session_id, "user", user_input)

        messages = [{"role": "system", "content": self.role["system"]}] + self.history

        result = {}
        done_event = threading.Event()

        def do_request():
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": "deepseek-v4-flash", "messages": messages},
            )
            data = response.json()
            result["answer"] = data["choices"][0]["message"]["content"]
            result["usage"]  = data.get("usage", {})
            done_event.set()

        thread = threading.Thread(target=do_request)
        thread.start()
        if not done_event.wait(timeout=3):
            print("Ну и задачка, всё ещё думаю :)")
        thread.join()

        answer = result["answer"]
        usage  = result.get("usage", {})

        self.history.append({"role": "assistant", "content": answer})
        save_message(self.session_id, "assistant", answer)

        self.total_input_tokens  += usage.get("prompt_tokens", 0)
        self.total_output_tokens += usage.get("completion_tokens", 0)
        self.request_count       += 1

        return answer


# ───────────────────────────────────────────
# CLI
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*55}")
    if title:
        print(f"  {title}")
        print(f"{'='*55}")

def show_help():
    print("""
Команды:
  /role     — сменить роль агента
  /reset    — сбросить память текущей сессии
  /history  — показать историю диалога
  /stats    — токены и стоимость
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
        return sid, "4", []

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<20} {'Роль':<22} {'Создана':<20} {'Сообщ.'}")
    print(f"  {'-'*4} {'-'*20} {'-'*22} {'-'*20} {'-'*6}")
    for sid, name, role_key, created_at, msg_count in sessions:
        role_name = ROLES.get(role_key, ROLES["4"])["name"]
        print(f"  {sid:<4} {name:<20} {role_name:<22} {created_at:<20} {msg_count}")

    print("\n  [N] Новая сессия")
    print("  [D] Удалить сессию")

    valid_ids = [str(s[0]) for s in sessions]

    while True:
        choice = input("\nВыбери ID сессии или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("Название новой сессии: ").strip() or f"Сессия {len(sessions)+1}"
            sid = create_session(name)
            return sid, "4", []
        elif choice == "D":
            del_id = input("ID сессии для удаления: ").strip()
            if del_id in valid_ids:
                delete_session(int(del_id))
                print(f"✅ Сессия {del_id} удалена.")
                return choose_or_create_session()
            else:
                print("Неверный ID.")
        elif choice in valid_ids:
            sid = int(choice)
            role_key, history = load_session(sid)
            return sid, role_key, history
        else:
            print(f"Введи ID из списка, N или D.")


# ───────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────

init_db()
divider("ЗАДАНИЕ 7 — Агент с памятью (SQLite)")

session_id, role_key, history = choose_or_create_session()
agent = Agent(session_id, role_key, history)

if history:
    print(f"\n✅ Сессия загружена. Сообщений в памяти: {len(history)}")
    print(f"   Роль: {agent.role['name']}")
    print(f"   Продолжаем с того места где остановились.\n")
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
                print(f"\n✅ Роль изменена: {agent.role['name']}\n")
                break
            print("Введи 1, 2, 3 или 4")

    elif user_input == "/reset":
        agent.reset()
        print("🗑️  Память сброшена. История удалена из базы.\n")

    elif user_input == "/history":
        if not agent.history:
            print("\n  История пуста.\n")
        else:
            divider("ИСТОРИЯ ДИАЛОГА")
            for msg in agent.history:
                role = "Ты" if msg["role"] == "user" else f"Агент ({agent.role['name']})"
                print(f"\n[{role}]\n{msg['content']}")
            print()

    elif user_input == "/stats":
        s = agent.stats()
        divider("СТАТИСТИКА")
        print(f"  Запросов     : {s['requests']}")
        print(f"  Input токены : {s['input_tokens']}")
        print(f"  Output токены: {s['output_tokens']}")
        print(f"  Всего токенов: {s['total_tokens']}")
        print(f"  Стоимость    : ${s['cost']:.6f}")
        print(f"  Роль         : {agent.role['name']}\n")

    elif user_input == "/sessions":
        sessions = list_sessions()
        divider("ВСЕ СЕССИИ")
        for sid, name, role_key, created_at, msg_count in sessions:
            mark = "◀ текущая" if sid == agent.session_id else ""
            print(f"  [{sid}] {name} | {ROLES.get(role_key, ROLES['4'])['name']} | {msg_count} сообщ. | {created_at} {mark}")
        print()

    else:
        answer = agent.run(user_input)
        print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
