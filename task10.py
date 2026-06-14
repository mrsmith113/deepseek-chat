import os
import sqlite3
import requests
import threading
import json
from datetime import datetime

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DB_FILE          = "task10_memory.db"
WINDOW_SIZE      = 2   # Sliding Window по умолчанию

INPUT_PRICE  = 0.14
OUTPUT_PRICE = 0.28

ROLES = {
    "1": {"name": "👶 Ребёнок",   "system": "Объясняй всё как семилетнему ребёнку."},
    "2": {"name": "🎓 Студент",   "system": "Объясняй как старшекурсник однокурснику."},
    "3": {"name": "🧑‍🏫 Профессор", "system": "Объясняй как профессор: определение → суть → примеры → выводы."},
    "4": {"name": "🤖 Ассистент", "system": "Ты полезный ассистент. Отвечай чётко и по делу."},
}

STRATEGIES = {
    "window":   "🪟 Sliding Window",
    "facts":    "📌 Sticky Facts",
    "branch":   "🌿 Branching",
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
            strategy   TEXT DEFAULT 'window',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER,
            branch        TEXT DEFAULT 'main',
            role          TEXT,
            content       TEXT,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            strategy      TEXT DEFAULT 'window',
            created_at    TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            key        TEXT,
            value      TEXT,
            updated_at TEXT,
            UNIQUE(session_id, key) ON CONFLICT REPLACE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            name       TEXT,
            message_id INTEGER,
            created_at TEXT
        )
    """)
    for col in ["strategy TEXT DEFAULT 'window'"]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col}")
        except:
            pass
    for col in ["branch TEXT DEFAULT 'main'", "strategy TEXT DEFAULT 'window'"]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col}")
        except:
            pass
    conn.commit()
    conn.close()

def create_session(name, role_key="4", strategy="window"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name,role_key,strategy,created_at) VALUES (?,?,?,?)",
              (name, role_key, strategy, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def list_sessions():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.role_key, s.strategy, s.created_at, COUNT(m.id)
        FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
        GROUP BY s.id ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id, branch="main"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT role_key, strategy FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    role_key = row[0] if row else "4"
    strategy = row[1] if row else "window"
    c.execute("SELECT role, content, input_tokens, output_tokens, COALESCE(strategy,'window') FROM messages "
              "WHERE session_id=? AND branch=? ORDER BY id", (session_id, branch))
    rows = c.fetchall()
    history   = [{"role": r, "content": ct} for r, ct, _, _, _ in rows]
    token_log = [(r, ct, it, ot, st) for r, ct, it, ot, st in rows]
    # факты
    c.execute("SELECT key, value FROM facts WHERE session_id=?", (session_id,))
    facts = {k: v for k, v in c.fetchall()}
    # ветки
    c.execute("SELECT DISTINCT branch FROM messages WHERE session_id=?", (session_id,))
    branches = [r[0] for r in c.fetchall()] or ["main"]
    conn.close()
    return role_key, strategy, history, token_log, facts, branches

def save_message(session_id, role, content, branch="main", input_tokens=0, output_tokens=0, strategy="window"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id,branch,role,content,input_tokens,output_tokens,strategy,created_at) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (session_id, branch, role, content, input_tokens, output_tokens, strategy,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id

def save_facts(session_id, facts):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    for k, v in facts.items():
        conn.execute("INSERT OR REPLACE INTO facts (session_id,key,value,updated_at) VALUES (?,?,?,?)",
                     (session_id, k, v, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def save_checkpoint(session_id, name, message_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("INSERT INTO checkpoints (session_id,name,message_id,created_at) VALUES (?,?,?,?)",
                 (session_id, name, message_id,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def list_checkpoints(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT id, name, message_id, created_at FROM checkpoints WHERE session_id=? ORDER BY id",
              (session_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def load_history_to_checkpoint(session_id, message_id, branch="main"):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages "
              "WHERE session_id=? AND branch=? AND id<=? ORDER BY id",
              (session_id, branch, message_id))
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "content": ct} for r, ct in rows]

def delete_session(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM facts WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM checkpoints WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

def update_session_strategy(session_id, strategy):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("UPDATE sessions SET strategy=? WHERE id=?", (strategy, session_id))
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
    def __init__(self, session_id, role_key, strategy, history, token_log, facts, branches):
        self.session_id   = session_id
        self.role_key     = role_key
        self.strategy     = strategy
        self.history      = history
        self.token_log    = token_log
        self.facts        = facts        # {key: value}
        self.branches     = branches
        self.branch       = "main"
        self.window_size  = WINDOW_SIZE

        self.total_input  = sum(r[2] for r in token_log)
        self.total_output = sum(r[3] for r in token_log)
        self.requests     = sum(1 for r in token_log if r[2] > 0)

        # статистика по стратегиям — восстанавливаем из лога
        self.strat_stats  = {s: {"input": 0, "output": 0, "requests": 0}
                             for s in STRATEGIES}
        for row in token_log:
            it = row[2]; ot = row[3]
            st = row[4] if len(row) > 4 else strategy
            if st not in self.strat_stats:
                st = "window"
            if it > 0:
                self.strat_stats[st]["input"]    += it
                self.strat_stats[st]["output"]   += ot
                self.strat_stats[st]["requests"] += 1

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.execute("UPDATE sessions SET role_key=? WHERE id=?", (key, self.session_id))
        conn.commit()
        conn.close()

    def set_strategy(self, strategy):
        self.strategy = strategy
        update_session_strategy(self.session_id, strategy)

    def reset(self):
        self.history      = []
        self.token_log    = []
        self.facts        = {}
        self.total_input  = 0
        self.total_output = 0
        self.requests     = 0
        self.strat_stats  = {s: {"input": 0, "output": 0, "requests": 0} for s in STRATEGIES}
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.execute("DELETE FROM messages WHERE session_id=?", (self.session_id,))
        conn.execute("DELETE FROM facts WHERE session_id=?", (self.session_id,))
        conn.execute("DELETE FROM checkpoints WHERE session_id=?", (self.session_id,))
        conn.commit()
        conn.close()

    # ── Построение контекста ──────────────────

    def build_window(self, user_input):
        """Стратегия 1: последние N сообщений"""
        tail = self.history[-(self.window_size * 2):] if len(self.history) > self.window_size * 2 else self.history
        msgs = [{"role": "system", "content": self.role["system"]}]
        msgs += tail
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def build_facts(self, user_input):
        """Стратегия 2: факты + последние N сообщений"""
        msgs = [{"role": "system", "content": self.role["system"]}]
        if self.facts:
            facts_text = "\n".join(f"• {k}: {v}" for k, v in self.facts.items())
            msgs.append({"role": "system",
                         "content": f"📌 Ключевые факты из диалога:\n{facts_text}"})
        tail = self.history[-(self.window_size * 2):]
        msgs += tail
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def build_branch(self, user_input):
        """Стратегия 3: история текущей ветки"""
        msgs = [{"role": "system", "content": self.role["system"]}]
        msgs += self.history
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def build_messages(self, user_input):
        if self.strategy == "window":
            return self.build_window(user_input)
        elif self.strategy == "facts":
            return self.build_facts(user_input)
        elif self.strategy == "branch":
            return self.build_branch(user_input)

    def max_tokens_for_strategy(self):
        """Window ограничивает ответ чтобы не тащить контекст"""
        if self.strategy == "window":
            return 300
        return None

    def update_facts_auto(self, user_input, answer):
        """Авто-обновление фактов после каждого сообщения"""
        existing = "\n".join(f"{k}: {v}" for k, v in self.facts.items()) if self.facts else "пусто"
        prompt = (
            f"Из этого диалога извлеки важные факты (цель, решения, предпочтения, ограничения, договорённости).\n"
            f"Текущие факты: {existing}\n\n"
            f"Пользователь: {user_input}\nАссистент: {answer}\n\n"
            f"Верни ТОЛЬКО JSON вида {{\"ключ\": \"значение\"}}. "
            f"Если новых фактов нет — верни пустой {{}}. Без пояснений."
        )
        result = call_api([{"role": "user", "content": prompt}], temperature=0)
        if result["answer"]:
            try:
                text = result["answer"].strip().replace("```json", "").replace("```", "").strip()
                new_facts = json.loads(text)
                if new_facts:
                    self.facts.update(new_facts)
                    save_facts(self.session_id, new_facts)
            except Exception:
                pass

    def run(self, user_input):
        messages   = self.build_messages(user_input)
        max_tokens = self.max_tokens_for_strategy()
        result     = call_api(messages, max_tokens=max_tokens)

        if result["error"]:
            print(f"\n❌ Ошибка: {result['error']}")
            return None

        answer     = result["answer"]
        usage      = result.get("usage", {})
        input_tok  = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)

        self.history.append({"role": "user",      "content": user_input})
        self.history.append({"role": "assistant",  "content": answer})

        msg_id = save_message(self.session_id, "user",      user_input,
                              self.branch, input_tok, 0, self.strategy)
        save_message(self.session_id, "assistant", answer,
                     self.branch, 0, output_tok, self.strategy)

        self.total_input  += input_tok
        self.total_output += output_tok
        self.requests     += 1
        self.strat_stats[self.strategy]["input"]    += input_tok
        self.strat_stats[self.strategy]["output"]   += output_tok
        if input_tok > 0:
            self.strat_stats[self.strategy]["requests"] += 1

        return answer, input_tok, output_tok, msg_id

# ───────────────────────────────────────────
# UI helpers
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def strategy_label(agent):
    return STRATEGIES.get(agent.strategy, agent.strategy)

def print_token_line(input_tok, output_tok, agent):
    cost = (input_tok / 1_000_000 * INPUT_PRICE +
            output_tok / 1_000_000 * OUTPUT_PRICE)
    total_tok = agent.total_input + agent.total_output
    branch_info = f" | ветка: {agent.branch}" if agent.strategy == "branch" else ""
    print(f"  📊 [{strategy_label(agent)}] вход: {input_tok} | выход: {output_tok} | "
          f"итого сессия: {total_tok:,} | ${cost:.6f}{branch_info}")


def get_session_stats(session_id):
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()
    c.execute("SELECT name, role_key, strategy FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    name, role_key, strategy = row
    c.execute("""
        SELECT COALESCE(strategy,'window'),
               SUM(input_tokens), SUM(output_tokens),
               COUNT(CASE WHEN role='assistant' THEN 1 END)
        FROM messages WHERE session_id=?
        GROUP BY COALESCE(strategy,'window')
    """, (session_id,))
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,))
    total_msgs = c.fetchone()[0]
    conn.close()

    stats = {s: {"input": 0, "output": 0, "requests": 0} for s in STRATEGIES}
    for strat, inp, out, reqs in rows:
        s = strat if strat in stats else "window"
        stats[s]["input"]    += inp or 0
        stats[s]["output"]   += out or 0
        stats[s]["requests"] += reqs or 0

    return {"name": name, "role": ROLES.get(role_key, ROLES["4"])["name"],
            "strategy": strategy, "total_msgs": total_msgs, "stats": stats}

def compare_sessions(agent):
    sessions = list_sessions()
    if len(sessions) < 2:
        print("\n  Нужно минимум 2 сессии.\n")
        return

    divider("ВЫБЕРИ СЕССИИ ДЛЯ СРАВНЕНИЯ (2 или 3)")
    for s_id, name, rk, strat, _, mc in sessions:
        mark = " ◀" if s_id == agent.session_id else ""
        slabel = STRATEGIES.get(strat, strat)
        print(f"  [{s_id}] {name} | {slabel} | {mc} сообщ.{mark}")

    valid = [str(s[0]) for s in sessions]
    chosen = []
    for i, label in enumerate(["Первая", "Вторая", "Третья (Enter = пропустить)"]):
        while True:
            val = input(f"  {label} сессия ID: ").strip()
            if val == "" and i == 2:
                break
            if val in valid and val not in chosen:
                chosen.append(val)
                break
            elif val in chosen:
                print("  Уже выбрана.")
            else:
                print("  Неверный ID.")

    stats_list = [(sid, get_session_stats(int(sid))) for sid in chosen]
    stats_list = [(sid, s) for sid, s in stats_list if s]

    def total(s, key):
        return sum(s["stats"][st][key] for st in STRATEGIES)

    def cost(s):
        return (total(s,"input") / 1_000_000 * INPUT_PRICE +
                total(s,"output") / 1_000_000 * OUTPUT_PRICE)

    def avg_in(s):
        r = total(s, "requests")
        return total(s, "input") // r if r else 0

    n = len(stats_list)
    w = 16
    titles = " ".join(f"{s['name'][:w]:>{w}}" for _, s in stats_list)
    divider(f"СРАВНЕНИЕ {n} СЕССИЙ")
    print(f"  {'Метрика':<24} {titles}")
    print(f"  {'-'*24} {(' ' + '-'*w) * n}")

    def row(label, vals):
        print(f"  {label:<24} " + " ".join(f"{v:>{w}}" for v in vals))

    row("Стратегия",    [STRATEGIES.get(s["strategy"], s["strategy"])[:w] for _, s in stats_list])
    row("Сообщений",    [s["total_msgs"] for _, s in stats_list])
    row("Запросов",     [f"{total(s,'requests'):,}" for _, s in stats_list])
    row("Вход токенов", [f"{total(s,'input'):,}" for _, s in stats_list])
    row("Выход токенов",[f"{total(s,'output'):,}" for _, s in stats_list])
    row("Вход/запрос",  [f"{avg_in(s):,}" for _, s in stats_list])
    row("Стоимость ($)", [f"{cost(s):.6f}" for _, s in stats_list])
    print()

def compare_branches(agent):
    """Задаёт один вопрос в каждой ветке и показывает ответы рядом"""
    if agent.strategy != "branch":
        print("\n  Доступно только в стратегии 🌿 Branching.\n")
        return
    if len(agent.branches) < 2:
        print("\n  Нужно минимум 2 ветки. Создай ветки через /branch\n")
        return

    divider("СРАВНЕНИЕ ВЕТОК")
    q = input("  Вопрос для всех веток: ").strip()
    if not q:
        return

    results = {}
    for branch in agent.branches:
        print(f"  Запрашиваю ветку '{branch}'...")
        # загружаем историю ветки
        _, _, hist, _, _, _ = load_session(agent.session_id, branch=branch)
        msgs = [{"role": "system", "content": agent.role["system"]}]
        msgs += hist
        msgs.append({"role": "user", "content": q})
        r = call_api(msgs)
        results[branch] = (r, len(hist))

    divider(f"ВОПРОС: {q}")
    for branch, (r, msg_count) in results.items():
        mark = " ◀ текущая" if branch == agent.branch else ""
        tok = r.get("usage", {}).get("prompt_tokens", 0)
        print(f"\n  🌿 Ветка '{branch}'{mark} | {msg_count} сообщ. | вход: {tok} tok")
        print(f"  {'-'*50}")
        answer = r.get("answer") or "❌ Ошибка"
        if len(answer) > 400:
            answer = answer[:400] + "..."
        print(f"  {answer}\n")

def compare_strategies(agent):
    """Прогоняет один вопрос через все три стратегии и показывает ответы рядом"""
    divider("СРАВНЕНИЕ СТРАТЕГИЙ — один вопрос, три ответа")
    q = input("  Введи вопрос для сравнения: ").strip()
    if not q:
        return

    results = {}
    for strat, label in STRATEGIES.items():
        print(f"\n  Запрашиваю {label}...")
        if strat == "window":
            msgs = [{"role": "system", "content": agent.role["system"]}]
            tail = agent.history[-(agent.window_size * 2):]
            msgs += tail
            msgs.append({"role": "user", "content": q})
            r = call_api(msgs, max_tokens=300)
        elif strat == "facts":
            msgs = [{"role": "system", "content": agent.role["system"]}]
            if agent.facts:
                facts_text = "\n".join(f"• {k}: {v}" for k, v in agent.facts.items())
                msgs.append({"role": "system", "content": f"📌 Ключевые факты:\n{facts_text}"})
            tail = agent.history[-(agent.window_size * 2):]
            msgs += tail
            msgs.append({"role": "user", "content": q})
            r = call_api(msgs)
        else:
            msgs = [{"role": "system", "content": agent.role["system"]}]
            msgs += agent.history
            msgs.append({"role": "user", "content": q})
            r = call_api(msgs)
        results[strat] = r

    divider(f"ВОПРОС: {q}")
    for strat, label in STRATEGIES.items():
        r = results[strat]
        tok = r.get("usage", {}).get("prompt_tokens", 0)
        print(f"\n  {label} (вход: {tok} tok):")
        print(f"  {'-'*50}")
        answer = r.get("answer") or "❌ Ошибка"
        # обрезаем для читаемости
        if len(answer) > 400:
            answer = answer[:400] + "..."
        print(f"  {answer}\n")


def show_help():
    print("""
Команды (можно вводить цифру или полное название):
  [1] /strategy         — сменить стратегию
  [2] /compare          — один вопрос через все три стратегии
  [3] /compare_branches — сравнить ветки (только branch)
  [4] /facts            — показать факты (только facts)
  [5] /checkpoint       — сохранить точку (только branch)
  [6] /branch           — создать ветку от checkpoint
  [7] /branches         — список веток и переключение
  [8] /stats            — токены по стратегиям
  [9] /role             — сменить роль
  [0] /reset            — сбросить всё
  [H] /history          — история диалога
  [S] /sessions         — список сессий + смена
  [C] /compare_sessions — сравнить две сессии по токенам
  [X] /exit             — выход
""")

SHORTCUT_MAP = {
    "1": "/strategy", "2": "/compare", "3": "/compare_branches",
    "4": "/facts", "5": "/checkpoint", "6": "/branch",
    "7": "/branches", "8": "/stats", "9": "/role",
    "0": "/reset", "h": "/history", "s": "/sessions", "x": "/exit", "c": "/compare_sessions",
}

def show_strategies():
    print("\nВыбери стратегию:")
    print("  [1] 🪟 Sliding Window — последние N сообщений")
    print("  [2] 📌 Sticky Facts   — факты + последние N сообщений")
    print("  [3] 🌿 Branching      — ветки диалога от checkpoint")

def print_stats_table(agent):
    divider("СРАВНЕНИЕ СТРАТЕГИЙ")
    w = 14
    print(f"  {'Метрика':<24} {'🪟 Window':>{w}} {'📌 Facts':>{w}} {'🌿 Branch':>{w}}")
    print(f"  {'-'*24} {'-'*w} {'-'*w} {'-'*w}")

    for label, key in [("Запросов", "requests"), ("Вход токенов", "input"), ("Выход токенов", "output")]:
        vals = [agent.strat_stats[s][key] for s in ["window", "facts", "branch"]]
        print(f"  {label:<24} {vals[0]:>{w},} {vals[1]:>{w},} {vals[2]:>{w},}")

    costs = []
    for s in ["window", "facts", "branch"]:
        st = agent.strat_stats[s]
        costs.append(st["input"] / 1_000_000 * INPUT_PRICE +
                     st["output"] / 1_000_000 * OUTPUT_PRICE)
    print(f"  {'Стоимость ($)':<24} {costs[0]:>{w}.6f} {costs[1]:>{w}.6f} {costs[2]:>{w}.6f}")

    avgs = []
    for s in ["window", "facts", "branch"]:
        st = agent.strat_stats[s]
        avgs.append(st["input"] // st["requests"] if st["requests"] else 0)
    print(f"  {'Вход/запрос (avg)':<24} {avgs[0]:>{w},} {avgs[1]:>{w},} {avgs[2]:>{w},}")
    print(f"\n  Текущая стратегия: {strategy_label(agent)}\n")

def choose_or_create_session():
    sessions = list_sessions()
    if not sessions:
        print("\nСессий нет. Создаём новую.")
        name = input("Название (Enter = 'Сессия 1'): ").strip() or "Сессия 1"
        return create_session(name), "4", "window", [], [], {}, ["main"]

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<20} {'Стратегия':<16} {'Сообщ.'}")
    print(f"  {'-'*4} {'-'*20} {'-'*16} {'-'*6}")
    for sid, name, rk, strat, _, mc in sessions:
        slabel = STRATEGIES.get(strat, strat)
        print(f"  {sid:<4} {name:<20} {slabel:<16} {mc}")

    print("\n  [N] Новая   [D] Удалить")
    valid = [str(s[0]) for s in sessions]

    while True:
        choice = input("\nВыбери ID или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("Название: ").strip() or f"Сессия {len(sessions)+1}"
            print("  Стратегия: [1] 🪟 Window  [2] 📌 Facts  [3] 🌿 Branch")
            strat_map = {"1": "window", "2": "facts", "3": "branch"}
            strat_ch = input("  Выбор [1-3] (Enter = Window): ").strip()
            strat = strat_map.get(strat_ch, "window")
            return create_session(name, strategy=strat), "4", strat, [], [], {}, ["main"]
        elif choice == "D":
            did = input("ID для удаления: ").strip()
            if did in valid:
                delete_session(int(did))
                print("✅ Удалено.")
                return choose_or_create_session()
        elif choice in valid:
            sid = int(choice)
            rk, strat, history, token_log, facts, branches = load_session(sid)
            return sid, rk, strat, history, token_log, facts, branches
        else:
            print("Неверный выбор.")

# ───────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────

init_db()
divider("ЗАДАНИЕ 10 — Стратегии управления контекстом")

result = choose_or_create_session()
sid, role_key, strategy, history, token_log, facts, branches = result
agent = Agent(sid, role_key, strategy, history, token_log, facts, branches)

print(f"\n✅ Стратегия: {strategy_label(agent)} | Роль: {agent.role['name']}")
print("   Введи /help для справки.\n")

last_msg_id = None

while True:
    try:
        user_input = input(f"[{strategy_label(agent)}] Ты: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nВыход.")
        break

    if not user_input:
        continue

    # shortcut: цифра/буква → команда
    user_input = SHORTCUT_MAP.get(user_input.lower(), user_input)

    if user_input == "/exit":
        print("\nПока!\n")
        break

    elif user_input == "/help":
        show_help()

    elif user_input == "/compare_sessions":
        compare_sessions(agent)

    elif user_input == "/compare":
        compare_strategies(agent)

    elif user_input == "/compare_branches":
        compare_branches(agent)

    elif user_input == "/strategy":
        show_strategies()
        while True:
            ch = input("Выбор [1-3]: ").strip()
            mapping = {"1": "window", "2": "facts", "3": "branch"}
            if ch in mapping:
                agent.set_strategy(mapping[ch])
                print(f"\n✅ Стратегия: {strategy_label(agent)}\n")
                break

    elif user_input == "/facts":
        if agent.facts:
            divider("📌 ФАКТЫ")
            for k, v in agent.facts.items():
                print(f"  • {k}: {v}")
            print()
        else:
            print("\n  Фактов нет. Переключись на стратегию facts и начни диалог.\n")

    elif user_input == "/checkpoint":
        if agent.strategy != "branch":
            print("\n  Checkpoint доступен только в стратегии 🌿 Branching. Используй /strategy\n")
        elif not last_msg_id:
            print("\n  Сначала напиши хотя бы одно сообщение.\n")
        else:
            cp_name = input("  Название checkpoint: ").strip() or f"cp_{datetime.now().strftime('%H%M%S')}"
            save_checkpoint(agent.session_id, cp_name, last_msg_id)
            print(f"\n  ✅ Checkpoint '{cp_name}' сохранён (message_id={last_msg_id})\n")

    elif user_input == "/branch":
        if agent.strategy != "branch":
            print("\n  Ветки доступны только в стратегии 🌿 Branching.\n")
        else:
            checkpoints = list_checkpoints(agent.session_id)
            if not checkpoints:
                print("\n  Нет сохранённых checkpoint. Используй /checkpoint\n")
            else:
                divider("СОЗДАТЬ ВЕТКУ")
                for cp_id, cp_name, msg_id, cp_time in checkpoints:
                    print(f"  [{cp_id}] {cp_name} | msg_id={msg_id} | {cp_time}")
                while True:
                    cp_choice = input("  Выбери checkpoint ID: ").strip()
                    valid_cp = [str(c[0]) for c in checkpoints]
                    if cp_choice in valid_cp:
                        break
                    print("  Неверный ID.")
                cp = next(c for c in checkpoints if str(c[0]) == cp_choice)
                branch_name = input("  Название новой ветки: ").strip() or f"branch_{datetime.now().strftime('%H%M%S')}"
                # восстанавливаем историю до checkpoint от ветки main
                source_branch = "main"
                agent.history  = load_history_to_checkpoint(agent.session_id, cp[2], source_branch)
                agent.branch   = branch_name
                if branch_name not in agent.branches:
                    agent.branches.append(branch_name)
                print(f"\n  ✅ Ветка '{branch_name}' создана от '{cp[1]}'\n"
                      f"  История откатилась до checkpoint. Продолжай диалог.\n")

    elif user_input == "/branches":
        if agent.strategy != "branch":
            print("\n  Ветки доступны только в стратегии 🌿 Branching.\n")
        else:
            divider("ВЕТКИ ДИАЛОГА")
            for b in agent.branches:
                mark = " ◀ текущая" if b == agent.branch else ""
                print(f"  • {b}{mark}")
            switch = input("\n  Переключиться на ветку (Enter = остаться): ").strip()
            if switch and switch in agent.branches:
                _, _, history, token_log, facts, _ = load_session(agent.session_id, branch=switch)
                agent.history   = history
                agent.branch    = switch
                print(f"\n  ✅ Переключились на ветку '{switch}' | {len(history)} сообщ.\n")
            elif switch:
                print("  Ветка не найдена.\n")

    elif user_input == "/stats":
        print_stats_table(agent)

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

    elif user_input == "/reset":
        agent.reset()
        last_msg_id = None
        print("🗑️  Всё сброшено.\n")

    elif user_input == "/history":
        if not agent.history:
            print("\n  История пуста.\n")
        else:
            divider(f"ИСТОРИЯ [{agent.branch}]")
            for m in agent.history:
                label = "Ты" if m["role"] == "user" else "Агент"
                print(f"\n[{label}]\n{m['content']}")
            print()

    elif user_input == "/sessions":
        sessions = list_sessions()
        divider("ВСЕ СЕССИИ")
        for s_id, name, rk, strat, _, mc in sessions:
            mark  = " ◀" if s_id == agent.session_id else ""
            slabel = STRATEGIES.get(strat, strat)
            print(f"  [{s_id}] {name} | {slabel} | {mc} сообщ.{mark}")
        print("\n  [N] Новая  [Enter] Остаться")
        valid = [str(s[0]) for s in sessions]
        switch = input("  Переключиться на ID (или Enter): ").strip().upper()
        if switch == "N":
            new_name = input("  Название: ").strip() or f"Сессия {len(sessions)+1}"
            print("  Стратегия: [1] 🪟 Window  [2] 📌 Facts  [3] 🌿 Branch")
            strat_map = {"1": "window", "2": "facts", "3": "branch"}
            strat_ch = input("  Выбор [1-3] (Enter = Window): ").strip()
            strat = strat_map.get(strat_ch, "window")
            new_sid = create_session(new_name, strategy=strat)
            agent.__init__(new_sid, "4", strat, [], [], {}, ["main"])
            last_msg_id = None
            print(f"\n✅ Новая сессия: {new_name} | {STRATEGIES[strat]}\n")
        elif switch in valid and int(switch) != agent.session_id:
            new_sid = int(switch)
            rk2, strat2, hist2, tlog2, facts2, branches2 = load_session(new_sid)
            agent.__init__(new_sid, rk2, strat2, hist2, tlog2, facts2, branches2)
            last_msg_id = None
            print(f"\n✅ Сессия {new_sid} загружена | стратегия: {strategy_label(agent)}\n")

    else:
        res = agent.run(user_input)
        if res:
            answer, input_tok, output_tok, msg_id = res
            last_msg_id = msg_id
            print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
            print_token_line(input_tok, output_tok, agent)
            # обновляем факты после записи в БД — избегаем database locked
            if agent.strategy == "facts":
                agent.update_facts_auto(user_input, answer)
                if agent.facts:
                    keys = list(agent.facts.keys())
                    print(f"  📌 Факты обновлены: {', '.join(keys[-3:])}")
            print()
