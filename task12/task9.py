import os
import sqlite3
import requests
import threading
from datetime import datetime

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
DB_FILE          = "agent_memory.db"

MODEL_CONTEXT_LIMIT = 64_000
INPUT_PRICE         = 0.14
OUTPUT_PRICE        = 0.28
TAIL_SIZE           = 6

ROLES = {
    "1": {"name": "👶 Ребёнок (7 лет)",  "system": "Объясняй всё как семилетнему ребёнку. Простые слова, короткие предложения, весёлые примеры."},
    "2": {"name": "🎓 Студент",           "system": "Объясняй как старшекурсник однокурснику. Термины с пояснением, примеры из учёбы."},
    "3": {"name": "🧑‍🏫 Профессор",        "system": "Объясняй как профессор. Строгая терминология: определение → суть → примеры → выводы."},
    "4": {"name": "🤖 Ассистент",         "system": "Ты полезный ассистент. Отвечай чётко и по делу."},
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
            summary    TEXT DEFAULT '',
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
            mode          TEXT DEFAULT 'normal',
            created_at    TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    for col in ["summary TEXT DEFAULT ''", "mode TEXT DEFAULT 'normal'"]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col}")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN mode TEXT DEFAULT 'normal'")
    except Exception:
        pass
    conn.commit()
    conn.close()

def create_session(name, role_key="4"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name, role_key, summary, created_at) VALUES (?,?,?,?)",
              (name, role_key, '', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def list_sessions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.role_key, s.created_at, COUNT(m.id),
               CASE WHEN s.summary!='' THEN 1 ELSE 0 END
        FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
        GROUP BY s.id ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role_key, summary FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    role_key = row[0] if row else "4"
    summary  = row[1] if row else ""
    c.execute("SELECT role, content, input_tokens, output_tokens, mode FROM messages "
              "WHERE session_id=? ORDER BY id", (session_id,))
    rows = c.fetchall()
    conn.close()
    messages  = [{"role": r, "content": ct} for r, ct, _, _, _ in rows]
    token_log = [(r, ct, it, ot, md) for r, ct, it, ot, md in rows]
    return role_key, summary, messages, token_log

def save_message(session_id, role, content, input_tokens=0, output_tokens=0, mode="normal"):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO messages (session_id,role,content,input_tokens,output_tokens,mode,created_at) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (session_id, role, content, input_tokens, output_tokens, mode,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def update_summary_db(session_id, summary):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE sessions SET summary=? WHERE id=?", (summary, session_id))
    conn.commit()
    conn.close()

def update_role_db(session_id, role_key):
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

def delete_messages_except_tail(session_id, keep_count):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
              (session_id, keep_count))
    keep_ids = [r[0] for r in c.fetchall()]
    if keep_ids:
        ph = ",".join("?" * len(keep_ids))
        conn.execute(f"DELETE FROM messages WHERE session_id=? AND id NOT IN ({ph})",
                     [session_id] + keep_ids)
    conn.commit()
    conn.close()

# ───────────────────────────────────────────
# API
# ───────────────────────────────────────────

def call_api(messages, temperature=0.7):
    result = {}
    done   = threading.Event()

    def do():
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": messages,
                  "temperature": temperature},
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
    def __init__(self, session_id, role_key, summary, history, token_log):
        self.session_id = session_id
        self.role_key   = role_key
        self.summary    = summary
        self.history    = history
        self.token_log  = token_log   # (role, content, input_tok, output_tok, mode)
        self.mode       = "normal"    # "normal" | "compress"

        # раздельная статистика
        self.stats_normal   = {"input": 0, "output": 0, "requests": 0}
        self.stats_compress = {"input": 0, "output": 0, "requests": 0}

        # восстанавливаем статистику из лога
        for _, _, it, ot, md in token_log:
            bucket = self.stats_compress if md == "compress" else self.stats_normal
            bucket["input"]  += it
            bucket["output"] += ot
            if it > 0:
                bucket["requests"] += 1

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key
        update_role_db(self.session_id, key)

    def set_mode(self, mode):
        self.mode = mode

    def reset(self):
        self.history             = []
        self.summary             = ""
        self.token_log           = []
        self.stats_normal        = {"input": 0, "output": 0, "requests": 0}
        self.stats_compress      = {"input": 0, "output": 0, "requests": 0}
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM messages WHERE session_id=?", (self.session_id,))
        conn.execute("UPDATE sessions SET summary='' WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()

    def history_tokens(self):
        chars = sum(len(m["content"]) for m in self.history)
        if self.summary:
            chars += len(self.summary)
        return chars // 4

    def context_pct(self):
        return self.history_tokens() / MODEL_CONTEXT_LIMIT * 100

    def build_messages_normal(self, user_input):
        msgs = [{"role": "system", "content": self.role["system"]}]
        msgs += self.history
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def build_messages_compress(self, user_input):
        msgs = [{"role": "system", "content": self.role["system"]}]
        if self.summary:
            msgs.append({"role": "system",
                         "content": f"📋 Резюме предыдущего диалога:\n{self.summary}"})
        tail = self.history[-TAIL_SIZE:] if len(self.history) > TAIL_SIZE else self.history
        msgs += tail
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def do_compress(self):
        """Сжать историю кроме хвоста в summary"""
        if len(self.history) <= TAIL_SIZE:
            return False, "Недостаточно сообщений (нужно больше хвоста)"

        to_compress = self.history[:-TAIL_SIZE]
        tail        = self.history[-TAIL_SIZE:]

        dialog = "\n".join(
            f"{'Пользователь' if m['role']=='user' else 'Ассистент'}: {m['content']}"
            for m in to_compress
        )
        if self.summary:
            prompt = (
                f"Есть уже накопленное резюме диалога:\n{self.summary}\n\n"
                f"Вот новые сообщения которые надо добавить к резюме:\n{dialog}\n\n"
                f"Обнови резюме: сохрани ВСЁ важное из старого резюме и добавь ключевые факты "
                f"из новых сообщений. Итог — единое связное резюме всего диалога (до 8 предложений)."
            )
        else:
            prompt = (
                f"Сделай краткое резюме этого диалога (3-5 предложений). "
                f"Сохрани все ключевые факты, темы и выводы по каждому вопросу:\n\n{dialog}"
            )

        tb     = self.history_tokens()
        result = call_api([{"role": "user", "content": prompt}], temperature=0)
        if result["error"]:
            return False, str(result["error"])

        self.summary = result["answer"]
        self.history = tail
        update_summary_db(self.session_id, self.summary)
        delete_messages_except_tail(self.session_id, TAIL_SIZE)

        u = result.get("usage", {})
        self.stats_compress["input"]  += u.get("prompt_tokens", 0)
        self.stats_compress["output"] += u.get("completion_tokens", 0)

        ta    = self.history_tokens()
        saved = tb - ta
        return True, (self.summary, tb, ta, saved)

    def run(self, user_input):
        # в режиме сжатия — авто-сжимаем когда накопилось 10 новых сообщений сверх хвоста
        if self.mode == "compress" and len(self.history) >= TAIL_SIZE + 10:
            print("\n  🔄 Авто-сжатие истории...")
            ok, info = self.do_compress()
            if ok:
                _, tb, ta, saved = info
                print(f"  ✅ Сжато: {tb} → {ta} токенов (сэкономлено ~{saved})")
                print(f"  📋 Резюме: {self.summary[:120]}...\n")

        if self.mode == "compress":
            messages = self.build_messages_compress(user_input)
        else:
            messages = self.build_messages_normal(user_input)

        result = call_api(messages)
        if result["error"]:
            print(f"\n❌ Ошибка: {result['error']}")
            return None

        answer     = result["answer"]
        usage      = result.get("usage", {})
        input_tok  = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)
        mode       = self.mode

        self.history.append({"role": "user",      "content": user_input})
        self.history.append({"role": "assistant",  "content": answer})
        save_message(self.session_id, "user",      user_input, input_tok, 0,          mode)
        save_message(self.session_id, "assistant", answer,     0,         output_tok, mode)

        bucket = self.stats_compress if mode == "compress" else self.stats_normal
        bucket["input"]    += input_tok
        bucket["output"]   += output_tok
        bucket["requests"] += 1

        return answer, input_tok, output_tok

# ───────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def mode_label(agent):
    if agent.mode == "compress":
        return "📋 СЖАТИЕ"
    return "📄 ОБЫЧНЫЙ"

def print_token_line(input_tok, output_tok, agent):
    pct        = agent.context_pct()
    bar_filled = min(int(pct / 5), 20)
    bar        = "█" * bar_filled + "░" * (20 - bar_filled)
    cost       = (input_tok / 1_000_000 * INPUT_PRICE +
                  output_tok / 1_000_000 * OUTPUT_PRICE)
    warn = "  ⚠️  БЛИЗКО!" if pct >= 80 else ("  🟡" if pct >= 50 else "")
    print(f"  📊 [{mode_label(agent)}] вход: {input_tok} | выход: {output_tok} | ${cost:.6f}")
    print(f"  🧠 [{bar}] {pct:.1f}%{warn}")

def print_stats_table(agent):
    n  = agent.stats_normal
    c  = agent.stats_compress
    ni = n["input"];  no = n["output"];  nr = n["requests"]
    ci = c["input"];  co = c["output"];  cr = c["requests"]

    # считаем экономию токенов на входе (если оба режима использовались)
    if nr > 0 and cr > 0:
        avg_in_normal   = ni / nr
        avg_in_compress = ci / cr
        saved_pct = (avg_in_normal - avg_in_compress) / avg_in_normal * 100 if avg_in_normal else 0
        economy = f"{saved_pct:+.1f}%"
    else:
        economy = "—"

    cost_n = (ni / 1_000_000 * INPUT_PRICE + no / 1_000_000 * OUTPUT_PRICE)
    cost_c = (ci / 1_000_000 * INPUT_PRICE + co / 1_000_000 * OUTPUT_PRICE)

    divider("СРАВНЕНИЕ РЕЖИМОВ")
    w = 16
    print(f"  {'Метрика':<22} {'📄 Обычный':>{w}} {'📋 Сжатие':>{w}} {'Экономия':>{w}}")
    print(f"  {'-'*22} {'-'*w} {'-'*w} {'-'*w}")
    print(f"  {'Запросов':<22} {nr:>{w}} {cr:>{w}} {'—':>{w}}")
    print(f"  {'Вход токенов (всего)':<22} {ni:>{w},} {ci:>{w},} {ni-ci:>+{w},}")
    print(f"  {'Выход токенов (всего)':<22} {no:>{w},} {co:>{w},} {no-co:>+{w},}")
    print(f"  {'Вход / запрос (avg)':<22} {ni//nr if nr else 0:>{w},} {ci//cr if cr else 0:>{w},} {economy:>{w}}")
    print(f"  {'Стоимость ($)':<22} {cost_n:>{w}.6f} {cost_c:>{w}.6f} {cost_n-cost_c:>+{w}.6f}")
    print()

def show_help():
    print("""
Команды:
  /mode       — переключить режим (обычный ↔ сжатие)
  /compress   — сжать историю вручную (только в режиме сжатия)
  /summary    — показать текущее резюме
  /stats      — таблица сравнения режимов
  /role       — сменить роль
  /reset      — сбросить всё
  /history    — история диалога
  /sessions   — список сессий + смена сессии
  /compare_sessions — сравнить статистику двух сессий
  /exit       — выход
""")

def show_roles():
    print("\nВыбери роль:")
    for k, r in ROLES.items():
        print(f"  [{k}] {r['name']}")

def get_session_stats(session_id):
    """Считаем статистику сессии из БД"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, role_key, summary FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    name, role_key, summary = row
    c.execute("""
        SELECT mode,
               SUM(input_tokens),  SUM(output_tokens),
               COUNT(CASE WHEN role='assistant' THEN 1 END)
        FROM messages WHERE session_id=?
        GROUP BY mode
    """, (session_id,))
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,))
    total_msgs = c.fetchone()[0]
    conn.close()

    stats = {"normal": {"input":0,"output":0,"requests":0},
             "compress": {"input":0,"output":0,"requests":0}}
    for mode, inp, out, reqs in rows:
        m = mode if mode in stats else "normal"
        stats[m]["input"]    += inp or 0
        stats[m]["output"]   += out or 0
        stats[m]["requests"] += reqs or 0

    return {
        "name":       name,
        "role":       ROLES.get(role_key, ROLES["4"])["name"],
        "has_summary": bool(summary),
        "total_msgs": total_msgs,
        "stats":      stats,
    }

def print_session_comparison(id1, id2):
    s1 = get_session_stats(id1)
    s2 = get_session_stats(id2)
    if not s1 or not s2:
        print("  Одна из сессий не найдена.")
        return

    divider(f"СРАВНЕНИЕ СЕССИЙ [{id1}] vs [{id2}]")

    def total(s, key):
        return s["stats"]["normal"][key] + s["stats"]["compress"][key]

    def cost(s):
        return (total(s,"input") / 1_000_000 * INPUT_PRICE +
                total(s,"output") / 1_000_000 * OUTPUT_PRICE)

    def avg_in(s):
        reqs = total(s,"requests")
        return total(s,"input") // reqs if reqs else 0

    w = 18
    print(f"  {'Метрика':<26} {('['+str(id1)+'] '+s1['name'])[:w]:>{w}} {('['+str(id2)+'] '+s2['name'])[:w]:>{w}}")
    print(f"  {'-'*26} {'-'*w} {'-'*w}")
    print(f"  {'Роль':<26} {s1['role'][:w]:>{w}} {s2['role'][:w]:>{w}}")
    print(f"  {'Сообщений':<26} {s1['total_msgs']:>{w}} {s2['total_msgs']:>{w}}")
    print(f"  {'Запросов к API':<26} {total(s1,'requests'):>{w}} {total(s2,'requests'):>{w}}")
    print(f"  {'Вход токенов':<26} {total(s1,'input'):>{w},} {total(s2,'input'):>{w},}")
    print(f"  {'Выход токенов':<26} {total(s1,'output'):>{w},} {total(s2,'output'):>{w},}")
    print(f"  {'Вход / запрос (avg)':<26} {avg_in(s1):>{w},} {avg_in(s2):>{w},}")
    print(f"  {'Стоимость ($)':<26} {cost(s1):>{w}.6f} {cost(s2):>{w}.6f}")
    print(f"  {'Режим сжатия':<26} {'есть 📋' if s1['has_summary'] else 'нет':>{w}} {'есть 📋' if s2['has_summary'] else 'нет':>{w}}")

    # разбивка по режимам если оба использовались
    for sid, s in [(id1, s1), (id2, s2)]:
        n = s["stats"]["normal"]
        c_ = s["stats"]["compress"]
        if n["requests"] > 0 and c_["requests"] > 0:
            print(f"\n  [{sid}] {s['name']} — разбивка по режимам:")
            print(f"  {'':4} {'Режим':<12} {'Запросов':>10} {'Вход':>10} {'Выход':>10}")
            print(f"  {'':4} {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
            print(f"  {'':4} {'📄 Обычный':<12} {n['requests']:>10} {n['input']:>10,} {n['output']:>10,}")
            print(f"  {'':4} {'📋 Сжатие':<12} {c_['requests']:>10} {c_['input']:>10,} {c_['output']:>10,}")
    print()


def choose_or_create_session():
    sessions = list_sessions()
    if not sessions:
        print("\nСессий нет. Создаём новую.")
        name = input("Название (Enter = 'Сессия 1'): ").strip() or "Сессия 1"
        return create_session(name), "4", "", [], []

    divider("СЕССИИ")
    print(f"  {'ID':<4} {'Название':<20} {'Роль':<22} {'Сообщ.':<8} {'Summary'}")
    print(f"  {'-'*4} {'-'*20} {'-'*22} {'-'*8} {'-'*7}")
    for sid, name, rk, _, mc, hs in sessions:
        rname = ROLES.get(rk, ROLES["4"])["name"]
        print(f"  {sid:<4} {name:<20} {rname:<22} {mc:<8} {'📋' if hs else '—'}")

    print("\n  [N] Новая   [D] Удалить")
    valid = [str(s[0]) for s in sessions]

    while True:
        choice = input("\nВыбери ID или [N/D]: ").strip().upper()
        if choice == "N":
            name = input("Название: ").strip() or f"Сессия {len(sessions)+1}"
            return create_session(name), "4", "", [], []
        elif choice == "D":
            did = input("ID для удаления: ").strip()
            if did in valid:
                delete_session(int(did))
                print("✅ Удалено.")
                return choose_or_create_session()
        elif choice in valid:
            sid = int(choice)
            rk, summary, history, token_log = load_session(sid)
            return sid, rk, summary, history, token_log
        else:
            print("Неверный выбор.")

# ───────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────

init_db()
divider("ЗАДАНИЕ 9 — Сжатие контекста")

sid, role_key, summary, history, token_log = choose_or_create_session()
agent = Agent(sid, role_key, summary, history, token_log)

print(f"\n✅ Роль: {agent.role['name']} | Режим: {mode_label(agent)}")
print("   Введи /help для справки.\n")

while True:
    try:
        user_input = input(f"[{mode_label(agent)}] Ты: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nВыход.")
        break

    if not user_input:
        continue

    elif user_input == "/exit":
        print("\nПока!\n")
        break

    elif user_input == "/help":
        show_help()

    elif user_input == "/mode":
        new_mode = "compress" if agent.mode == "normal" else "normal"
        agent.set_mode(new_mode)
        print(f"\n✅ Режим: {mode_label(agent)}\n")

    elif user_input == "/compress":
        if agent.mode != "compress":
            print("\n  Сначала переключись в режим сжатия: /mode\n")
        elif len(agent.history) <= TAIL_SIZE:
            print(f"\n  Нужно больше {TAIL_SIZE} сообщений.\n")
        else:
            print("\n  🔄 Сжимаю...")
            ok, info = agent.do_compress()
            if ok:
                _, tb, ta, saved = info
                print(f"  ✅ Готово: {tb} → {ta} токенов (сэкономлено ~{saved})")
                print(f"\n  📋 Резюме:\n  {agent.summary}\n")
            else:
                print(f"  ❌ {info}\n")

    elif user_input == "/summary":
        if agent.summary:
            divider("📋 РЕЗЮМЕ")
            print(agent.summary)
            print(f"\n  ~{len(agent.summary)//4} токенов\n")
        else:
            print("\n  Резюме нет. Используй /compress в режиме сжатия.\n")

    elif user_input == "/stats":
        print_stats_table(agent)

    elif user_input == "/role":
        show_roles()
        while True:
            ch = input("Выбор [1-4]: ").strip()
            if ch in ROLES:
                agent.set_role(ch)
                print(f"\n✅ Роль: {agent.role['name']}\n")
                break

    elif user_input == "/reset":
        agent.reset()
        print("🗑️  Всё сброшено.\n")

    elif user_input == "/history":
        if not agent.history:
            print("\n  История пуста.\n")
        else:
            divider("ИСТОРИЯ")
            for m in agent.history:
                label = "Ты" if m["role"] == "user" else "Агент"
                print(f"\n[{label}]\n{m['content']}")
            print()

    elif user_input == "/compare_sessions":
        sessions = list_sessions()
        if len(sessions) < 2:
            print("\n  Нужно минимум 2 сессии для сравнения.\n")
        else:
            divider("ВЫБЕРИ ДВЕ СЕССИИ ДЛЯ СРАВНЕНИЯ")
            for s_id, name, rk, _, mc, hs in sessions:
                mark = " ◀" if s_id == agent.session_id else ""
                print(f"  [{s_id}] {name} | {mc} сообщ.{mark}")
            valid = [str(s[0]) for s in sessions]
            while True:
                id1 = input("  Первая сессия ID: ").strip()
                if id1 in valid:
                    break
                print("  Неверный ID.")
            while True:
                id2 = input("  Вторая сессия ID: ").strip()
                if id2 in valid and id2 != id1:
                    break
                print("  Неверный ID (или совпадает с первым).")
            print_session_comparison(int(id1), int(id2))

    elif user_input == "/sessions":
        sessions = list_sessions()
        divider("ВСЕ СЕССИИ")
        for s_id, name, rk, _, mc, hs in sessions:
            mark = " ◀ текущая" if s_id == agent.session_id else ""
            sum_mark = "📋" if hs else "—"
            print(f"  [{s_id}] {name} | {mc} сообщ. | {sum_mark}{mark}")
        print("\n  [N] Новая сессия  [Enter] Остаться")
        valid = [str(s[0]) for s in sessions]
        switch = input("  Переключиться на ID (или Enter): ").strip().upper()
        if switch == "N":
            new_name = input("  Название: ").strip() or f"Сессия {len(sessions)+1}"
            new_sid = create_session(new_name)
            agent.__init__(new_sid, "4", "", [], [])
            print(f"\n✅ Новая сессия: {new_name}\n")
        elif switch in valid and int(switch) != agent.session_id:
            new_sid = int(switch)
            rk2, summary2, history2, tlog2 = load_session(new_sid)
            agent.__init__(new_sid, rk2, summary2, history2, tlog2)
            print(f"\n✅ Сессия {new_sid} загружена | {len(history2)} сообщ. | роль: {agent.role['name']}\n")
        elif switch:
            print("  Остаёмся в текущей сессии.\n")
    else:
        result = agent.run(user_input)
        if result:
            answer, input_tok, output_tok = result
            print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
            print_token_line(input_tok, output_tok, agent)
            print()
