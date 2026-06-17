import sqlite3
from datetime import datetime

DB_FILE = "hornest.db"


def get_conn():
    return sqlite3.connect(DB_FILE, timeout=10)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            agent_key  TEXT DEFAULT 'chat',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          INTEGER,
            agent_key           TEXT DEFAULT 'chat',
            role                TEXT,
            content             TEXT,
            input_tokens        INTEGER DEFAULT 0,
            output_tokens       INTEGER DEFAULT 0,
            cached_tokens       INTEGER DEFAULT 0,
            created_at          TEXT
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
    # Долговременная + профили — глобальные
    c.execute("""
        CREATE TABLE IF NOT EXISTS long_term_memory (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key        TEXT UNIQUE,
            value      TEXT,
            category   TEXT DEFAULT 'general',
            updated_at TEXT
        )
    """)
    # Профили пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT UNIQUE,
            data       TEXT,
            is_active  INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── Sessions ──────────────────────────────

def create_session(name, agent_key="chat"):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name,agent_key,created_at) VALUES (?,?,?)",
              (name, agent_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid

def list_sessions():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT s.id, s.name, s.agent_key, s.created_at, COUNT(m.id)
        FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
        GROUP BY s.id ORDER BY s.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def load_session(session_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT agent_key FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    agent_key = row[0] if row else "chat"
    c.execute("SELECT role, content, input_tokens, output_tokens, cached_tokens "
              "FROM messages WHERE session_id=? ORDER BY id", (session_id,))
    rows = c.fetchall()
    history   = [{"role": r, "content": ct} for r, ct, _, _, _ in rows]
    token_log = [(r, ct, it, ot, ca) for r, ct, it, ot, ca in rows]
    c.execute("SELECT key, value FROM working_memory WHERE session_id=?", (session_id,))
    working = {k: v for k, v in c.fetchall()}
    conn.close()
    return agent_key, history, token_log, working

def delete_session(session_id):
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM working_memory WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

def update_session_agent(session_id, agent_key):
    conn = get_conn()
    conn.execute("UPDATE sessions SET agent_key=? WHERE id=?", (agent_key, session_id))
    conn.commit()
    conn.close()


# ── Messages ──────────────────────────────

def save_message(session_id, agent_key, role, content,
                 input_tokens=0, output_tokens=0, cached_tokens=0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO messages "
              "(session_id,agent_key,role,content,input_tokens,output_tokens,cached_tokens,created_at) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (session_id, agent_key, role, content,
               input_tokens, output_tokens, cached_tokens,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


# ── Working memory ────────────────────────

def save_working(session_id, key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO working_memory (session_id,key,value,updated_at) VALUES (?,?,?,?)",
                 (session_id, key, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def delete_working(session_id, key):
    conn = get_conn()
    conn.execute("DELETE FROM working_memory WHERE session_id=? AND key=?", (session_id, key))
    conn.commit()
    conn.close()

def clear_working(session_id):
    conn = get_conn()
    conn.execute("DELETE FROM working_memory WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()


# ── Long-term memory ──────────────────────

def load_long_term():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key, value, category FROM long_term_memory ORDER BY category, key")
    rows = c.fetchall()
    conn.close()
    return rows

def save_long_term(key, value, category="general"):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO long_term_memory (key,value,category,updated_at) VALUES (?,?,?,?)",
                 (key, value, category, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def delete_long_term(key):
    conn = get_conn()
    conn.execute("DELETE FROM long_term_memory WHERE key=?", (key,))
    conn.commit()
    conn.close()


# ── Profiles ──────────────────────────────

def list_profiles():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, data, is_active FROM profiles ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def save_profile(name, data, set_active=False):
    import json
    conn = get_conn()
    if set_active:
        conn.execute("UPDATE profiles SET is_active=0")
    conn.execute("INSERT OR REPLACE INTO profiles (name,data,is_active,created_at) VALUES (?,?,?,?)",
                 (name, json.dumps(data, ensure_ascii=False),
                  1 if set_active else 0,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def load_active_profile():
    import json
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name, data FROM profiles WHERE is_active=1 LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], json.loads(row[1])
    return None, None

def set_active_profile(profile_name):
    conn = get_conn()
    conn.execute("UPDATE profiles SET is_active=0")
    conn.execute("UPDATE profiles SET is_active=1 WHERE name=?", (profile_name,))
    conn.commit()
    conn.close()

def delete_profile(profile_name):
    conn = get_conn()
    conn.execute("DELETE FROM profiles WHERE name=?", (profile_name,))
    conn.commit()
    conn.close()

def profiles_exist():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM profiles")
    count = c.fetchone()[0]
    conn.close()
    return count > 0
