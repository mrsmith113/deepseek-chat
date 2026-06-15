import os
import sqlite3
import requests
import threading
import json
from datetime import datetime

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DB_FILE          = "task11_memory.db"
SHORT_TERM_SIZE  = 6   # последних сообщений в краткосрочной

INPUT_PRICE  = 0.14
OUTPUT_PRICE = 0.28

ROLES = {
    "1": {"name": "👶 Ребёнок",   "system": "Объясняй всё как семилетнему ребёнку."},
    "2": {"name": "🎓 Студент",   "system": "Объясняй как старшекурсник однокурснику."},
    "3": {"name": "🧑‍🏫 Профессор", "system": "Объясняй как профессор: определение → суть → примеры → выводы."},
    "4": {"name": "🤖 Ассистент", "system": "Ты полезный ассистент. Отвечай чётко и по делу."},
}

# ───────────────────────────────────────────
# БД
# ───────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
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
            created_at    TEXT
        )
    """)
    # Рабочая память — привязана к сессии
    c.execute("""
        CREATE TABLE IF NOT EXISTS working_memory (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            key        TEXT,
            value      TEXT,
            updated_at TEXT,
            UNIQUE(session_id, key) ON CONFLICT REPLACE
        )
    """)
    # Долговременная память — глобальная, без session_id
    c.execute("""
        CREATE TABLE IF NOT EXISTS long_term_memory (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key        TEXT UNIQUE,
            value      TEXT,
            category   TEXT DEFAULT 'general',
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def create_session(name, role_key="4"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name,role_key,created_at) VALUES (?,?,?)",
              (name, role_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def list_sessions():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.role_key, s.created_at, COUNT(m.id)
        FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
        GROUP BY s.id ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT role_key FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    role_key = row[0] if row else "4"
    c.execute("SELECT role, content, input_tokens, output_tokens FROM messages "
              "WHERE session_id=? ORDER BY id", (session_id,))
    rows = c.fetchall()
    history   = [{"role": r, "content": ct} for r, ct, _, _ in rows]
    token_log = [(r, ct, it, ot) for r, ct, it, ot in rows]
    # рабочая память сессии
    c.execute("SELECT key, value FROM working_memory WHERE session_id=?", (session_id,))
    working = {k: v for k, v in c.fetchall()}
    conn.close()
    return role_key, history, token_log, working

def save_message(session_id, role, content, input_tokens=0, output_tokens=0):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("INSERT INTO messages (session_id,role,content,input_tokens,output_tokens,created_at) "
                 "VALUES (?,?,?,?,?,?)",
                 (session_id, role, content, input_tokens, output_tokens,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def load_long_term():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT key, value, category FROM long_term_memory ORDER BY category, key")
    rows = c.fetchall()
    conn.close()
    return rows  # [(key, value, category)]

def save_long_term(key, value, category="general"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("INSERT OR REPLACE INTO long_term_memory (key,value,category,updated_at) VALUES (?,?,?,?)",
                 (key, value, category, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def delete_long_term(key):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("DELETE FROM long_term_memory WHERE key=?", (key,))
    conn.commit()
    conn.close()

def save_working(session_id, key, value):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("INSERT OR REPLACE INTO working_memory (session_id,key,value,updated_at) VALUES (?,?,?,?)",
                 (session_id, key, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def delete_working(session_id, key):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("DELETE FROM working_memory WHERE session_id=? AND key=?", (session_id, key))
    conn.commit()
    conn.close()

def clear_working(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("DELETE FROM working_memory WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM working_memory WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

def update_role_db(session_id, role_key):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("UPDATE sessions SET role_key=? WHERE id=?", (role_key, session_id))
    conn.commit()
    conn.close()

# ───────────────────────────────────────────
# API
# ───────────────────────────────────────────

def call_api(messages, temperature=0.7, max_tokens=None):
    result = {}
    done   = threading.Event()

    def do():
        body = {"model": "deepseek-chat", "messages": messages, "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json=body,
        )
        d = r.json()
        result["answer"] = d["choices"][0]["message"]["content"] if "choices" in d else None
        result["usage"]  = d.get("usage", {})
        result["error"]  = d.get("error") if "choices" not in d else None
        done.set()

    t = threading.Thread(target=do)
    t.start()
    if not done.wait(timeout=3):
        print("Ну и задачка, всё ещё думаю :)")
    t.join()
    return result

# ───────────────────────────────────────────
# Агент
# ───────────────────────────────────────────

class Agent:
    def __init__(self, session_id, role_key, history, token_log, working):
        self.session_id   = session_id
        self.role_key     = role_key
        self.history      = history        # 🔵 Short-term (полная история)
        self.working      = working        # 🟡 Working memory
        self.token_log    = token_log
        self.total_input  = sum(r[2] for r in token_log)
        self.total_output = sum(r[3] for r in token_log)
        self.requests     = sum(1 for r in token_log if r[2] > 0)

        # 🟢 Long-term грузится глобально
        lt = load_long_term()
        self.long_term = {k: (v, cat) for k, v, cat in lt}

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key
        update_role_db(self.session_id, key)

    def reload_long_term(self):
        lt = load_long_term()
        self.long_term = {k: (v, cat) for k, v, cat in lt}

    def build_messages(self, user_input):
        msgs = [{"role": "system", "content": self.role["system"]}]

        # 🟢 Long-term
        if self.long_term:
            lt_text = "\n".join(f"• [{cat}] {k}: {v}" for k, (v, cat) in self.long_term.items())
            msgs.append({"role": "system",
                         "content": f"🟢 Долговременная память (профиль, решения, знания):\n{lt_text}"})

        # 🟡 Working memory
        if self.working:
            wm_text = "\n".join(f"• {k}: {v}" for k, v in self.working.items())
            msgs.append({"role": "system",
                         "content": f"🟡 Рабочая память (текущая задача):\n{wm_text}"})

        # 🔵 Short-term — последние N сообщений
        tail = self.history[-(SHORT_TERM_SIZE * 2):]
        msgs += tail
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def extract_suggestions(self, user_input, answer):
        """Просим модель предложить что сохранить в память"""
        prompt = (
            f"Из этого обмена извлеки важные факты которые стоит запомнить.\n"
            f"Пользователь: {user_input}\nАссистент: {answer}\n\n"
            f"Верни JSON список объектов: "
            f"[{{\"key\": \"ключ\", \"value\": \"значение\", \"layer\": \"long\" или \"working\"}}]\n"
            f"Правила:\n"
            f"- long: профиль пользователя, важные решения, постоянные знания\n"
            f"- working: детали текущей задачи, временные данные\n"
            f"Если нечего запоминать — верни []\n"
            f"Только JSON, без пояснений."
        )
        r = call_api([{"role": "user", "content": prompt}], temperature=0, max_tokens=300)
        if r["answer"]:
            try:
                text = r["answer"].strip().replace("```json", "").replace("```", "").strip()
                return json.loads(text)
            except:
                pass
        return []

    def run(self, user_input):
        messages = self.build_messages(user_input)
        result   = call_api(messages)

        if result["error"]:
            print(f"\n❌ Ошибка: {result['error']}")
            return None

        answer     = result["answer"]
        usage      = result.get("usage", {})
        input_tok  = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)

        self.history.append({"role": "user",      "content": user_input})
        self.history.append({"role": "assistant",  "content": answer})
        save_message(self.session_id, "user",      user_input, input_tok, 0)
        save_message(self.session_id, "assistant", answer,     0, output_tok)

        self.total_input  += input_tok
        self.total_output += output_tok
        self.requests     += 1

        return answer, input_tok, output_tok

# ───────────────────────────────────────────
# UI helpers
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def print_token_line(input_tok, output_tok, agent):
    cost = (input_tok / 1_000_000 * INPUT_PRICE +
            output_tok / 1_000_000 * OUTPUT_PRICE)
    lt_count = len(agent.long_term)
    wm_count = len(agent.working)
    st_count = len(agent.history)
    print(f"  📊 вход: {input_tok} | выход: {output_tok} | ${cost:.6f}")
    print(f"  🧠 🟢 long: {lt_count} | 🟡 work: {wm_count} | 🔵 short: {st_count} сообщ.")

def show_memory(agent):
    divider("ПАМЯТЬ АГЕНТА")

    print(f"\n  🟢 ДОЛГОВРЕМЕННАЯ (глобальная, все сессии):")
    if agent.long_term:
        for k, (v, cat) in agent.long_term.items():
            print(f"     [{cat}] {k}: {v}")
    else:
        print("     пусто")

    print(f"\n  🟡 РАБОЧАЯ (только эта сессия):")
    if agent.working:
        for k, v in agent.working.items():
            print(f"     {k}: {v}")
    else:
        print("     пусто")

    print(f"\n  🔵 КРАТКОСРОЧНАЯ (текущий диалог):")
    tail = agent.history[-(SHORT_TERM_SIZE * 2):]
    if tail:
        for m in tail:
            label = "Ты" if m["role"] == "user" else "Агент"
            preview = m["content"][:80].replace("\n", " ")
            print(f"     [{label}] {preview}{'...' if len(m['content'])>80 else ''}")
    else:
        print("     пусто")
    print()

def handle_suggestions(agent, suggestions):
    """Показываем предложения и спрашиваем что сохранить"""
    if not suggestions:
        return

    print(f"\n  💡 Предлагаю сохранить в память:")
    for i, s in enumerate(suggestions, 1):
        layer = "🟢 долговременная" if s["layer"] == "long" else "🟡 рабочая"
        print(f"     [{i}] \"{s['key']}: {s['value']}\" → {layer}")

    print(f"  Выбор (1 2 3... или 'all' или Enter): ", end="")
    choice = input().strip().lower()

    if not choice:
        return

    indices = []
    if choice == "all":
        indices = list(range(len(suggestions)))
    else:
        for c in choice.split():
            if c.isdigit() and 1 <= int(c) <= len(suggestions):
                indices.append(int(c) - 1)

    for i in indices:
        s = suggestions[i]
        if s["layer"] == "long":
            # спрашиваем категорию
            cat = input(f"  Категория для '{s['key']}' (profile/decision/knowledge/general): ").strip()
            cat = cat if cat in ["profile", "decision", "knowledge", "general"] else "general"
            save_long_term(s["key"], s["value"], cat)
            agent.long_term[s["key"]] = (s["value"], cat)
            print(f"  ✅ → 🟢 долговременная [{cat}]: {s['key']}")
        else:
            save_working(agent.session_id, s["key"], s["value"])
            agent.working[s["key"]] = s["value"]
            print(f"  ✅ → 🟡 рабочая: {s['key']}")

def show_help():
    print("""
Команды:
  [1] /memory          — показать все три слоя памяти
  [2] /remember        — вручную сохранить в долговременную
  [3] /forget          — удалить из долговременной
  [4] /working set     — записать в рабочую память
  [5] /working clear   — очистить рабочую память
  [6] /role            — сменить роль
  [7] /stats           — токены и стоимость
  [8] /history         — полная история диалога
  [9] /sessions        — список сессий + смена
  [0] /reset           — сбросить краткосрочную и рабочую
  [X] /exit            — выход
""")

SHORTCUT_MAP = {
    "1": "/memory", "2": "/remember", "3": "/forget",
    "4": "/working set", "5": "/working clear", "6": "/role",
    "7": "/stats", "8": "/history", "9": "/sessions",
    "0": "/reset", "x": "/exit",
}

def choose_or_create_session():
    sessions = list_sessions()
    if not sessions:
        print("\nСессий нет. Создаём новую.")
        name = input("Название (Enter = 'Сессия 1'): ").strip() or "Сессия 1"
        return create_session(name), "4", [], [], {}

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<24} {'Роль':<22} {'Сообщ.'}")
    print(f"  {'-'*4} {'-'*24} {'-'*22} {'-'*6}")
    for sid, name, rk, created_at, mc in sessions:
        rname = ROLES.get(rk, ROLES["4"])["name"]
        print(f"  {sid:<4} {name:<24} {rname:<22} {mc}")

    print("\n  [N] Новая   [D] Удалить")
    valid = [str(s[0]) for s in sessions]

    while True:
        choice = input("\nВыбери ID или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("Название: ").strip() or f"Сессия {len(sessions)+1}"
            return create_session(name), "4", [], [], {}
        elif choice == "D":
            did = input("ID для удаления: ").strip()
            if did in valid:
                delete_session(int(did))
                print("✅ Удалено.")
                return choose_or_create_session()
        elif choice in valid:
            sid = int(choice)
            rk, history, token_log, working = load_session(sid)
            return sid, rk, history, token_log, working
        else:
            print("Неверный выбор.")

# ───────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────

init_db()
divider("ЗАДАНИЕ 11 — Модель памяти агента")

sid, role_key, history, token_log, working = choose_or_create_session()
agent = Agent(sid, role_key, history, token_log, working)

lt_count = len(agent.long_term)
print(f"\n✅ Роль: {agent.role['name']}")
print(f"   🟢 Долговременная: {lt_count} записей (глобально)")
print(f"   🟡 Рабочая:        {len(agent.working)} записей (эта сессия)")
print(f"   🔵 Краткосрочная:  {len(agent.history)} сообщений")
print("   Введи /help для справки.\n")

while True:
    try:
        user_input = input("Ты: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nВыход.")
        break

    if not user_input:
        continue

    user_input = SHORTCUT_MAP.get(user_input.lower(), user_input)

    if user_input == "/exit":
        print("\nПока!\n")
        break

    elif user_input == "/help":
        show_help()

    elif user_input == "/memory":
        show_memory(agent)

    elif user_input == "/remember":
        key   = input("  Ключ: ").strip()
        value = input("  Значение: ").strip()
        cat   = input("  Категория (profile/decision/knowledge/general): ").strip()
        cat   = cat if cat in ["profile", "decision", "knowledge", "general"] else "general"
        save_long_term(key, value, cat)
        agent.long_term[key] = (value, cat)
        print(f"  ✅ Сохранено в 🟢 долговременную [{cat}]: {key}\n")

    elif user_input == "/forget":
        if not agent.long_term:
            print("\n  Долговременная память пуста.\n")
        else:
            print("\n  🟢 Долговременная память:")
            keys = list(agent.long_term.keys())
            for i, k in enumerate(keys, 1):
                v, cat = agent.long_term[k]
                print(f"  [{i}] [{cat}] {k}: {v}")
            choice = input("  Удалить номер (или Enter = отмена): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(keys):
                k = keys[int(choice)-1]
                delete_long_term(k)
                del agent.long_term[k]
                print(f"  ✅ Удалено: {k}\n")

    elif user_input == "/working set":
        key   = input("  Ключ: ").strip()
        value = input("  Значение: ").strip()
        save_working(agent.session_id, key, value)
        agent.working[key] = value
        print(f"  ✅ Сохранено в 🟡 рабочую: {key}\n")

    elif user_input == "/working clear":
        clear_working(agent.session_id)
        agent.working = {}
        print("  🗑️  Рабочая память очищена.\n")

    elif user_input == "/role":
        print("\nВыбери роль:")
        for k, r in ROLES.items():
            print(f"  [{k}] {r['name']}")
        while True:
            ch = input("Выбор [1-4]: ").strip()
            if ch in ROLES:
                agent.set_role(ch)
                print(f"\n✅ Роль: {agent.role['name']}\n")
                break

    elif user_input == "/stats":
        cost = (agent.total_input / 1_000_000 * INPUT_PRICE +
                agent.total_output / 1_000_000 * OUTPUT_PRICE)
        divider("СТАТИСТИКА")
        print(f"  Запросов     : {agent.requests}")
        print(f"  Input токены : {agent.total_input:,}")
        print(f"  Output токены: {agent.total_output:,}")
        print(f"  Стоимость    : ${cost:.6f}")
        print(f"  🟢 Long-term : {len(agent.long_term)} записей")
        print(f"  🟡 Working   : {len(agent.working)} записей")
        print(f"  🔵 Short-term: {len(agent.history)} сообщений\n")

    elif user_input == "/history":
        if not agent.history:
            print("\n  История пуста.\n")
        else:
            divider("🔵 КРАТКОСРОЧНАЯ ПАМЯТЬ (полная история)")
            for m in agent.history:
                label = "Ты" if m["role"] == "user" else "Агент"
                print(f"\n[{label}]\n{m['content']}")
            print()

    elif user_input == "/reset":
        agent.history = []
        clear_working(agent.session_id)
        agent.working = {}
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.execute("DELETE FROM messages WHERE session_id=?", (agent.session_id,))
        conn.commit()
        conn.close()
        print("🗑️  Краткосрочная и рабочая память сброшены. Долговременная сохранена.\n")

    elif user_input == "/sessions":
        sessions = list_sessions()
        divider("ВСЕ СЕССИИ")
        for s_id, name, rk, _, mc in sessions:
            mark = " ◀" if s_id == agent.session_id else ""
            print(f"  [{s_id}] {name} | {mc} сообщ.{mark}")
        print("\n  [N] Новая  [Enter] Остаться")
        valid = [str(s[0]) for s in sessions]
        switch = input("  Переключиться на ID (или Enter): ").strip().upper()
        if switch == "N":
            new_name = input("  Название: ").strip() or f"Сессия {len(sessions)+1}"
            new_sid  = create_session(new_name)
            rk2, hist2, tlog2, work2 = load_session(new_sid)[0:4]
            agent.__init__(new_sid, rk2, hist2, tlog2, work2)
            print(f"\n✅ Новая сессия: {new_name}")
            print(f"   🟢 Долговременная память перенесена: {len(agent.long_term)} записей\n")
        elif switch in valid and int(switch) != agent.session_id:
            new_sid = int(switch)
            rk2, hist2, tlog2, work2 = load_session(new_sid)
            agent.__init__(new_sid, rk2, hist2, tlog2, work2)
            print(f"\n✅ Сессия {new_sid} загружена")
            print(f"   🟢 Долговременная: {len(agent.long_term)} | 🟡 Рабочая: {len(agent.working)}\n")

    else:
        res = agent.run(user_input)
        if res:
            answer, input_tok, output_tok = res
            print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
            print_token_line(input_tok, output_tok, agent)

            # авто-предложение что сохранить
            print("\n  ⏳ Анализирую что стоит запомнить...")
            suggestions = agent.extract_suggestions(user_input, answer)
            if suggestions:
                handle_suggestions(agent, suggestions)
            else:
                print("  (нечего запоминать)")
            print()
