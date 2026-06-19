"""
Инварианты — жёсткие ограничения, которые агент не имеет права нарушать.

Хранятся в SQLite отдельно от диалога.
Инжектируются в системный промпт перед каждым запросом.
Агент обязан возвращать [CONFLICT: ...] при обнаружении нарушения.
"""

from db import get_conn
from datetime import datetime

# ── Категории инвариантов ─────────────────

INVARIANT_CATEGORIES = {
    "architecture": "🏗  Архитектура",
    "stack":        "🧱 Стек",
    "business":     "💼 Бизнес-правила",
    "security":     "🔒 Безопасность",
    "general":      "📌 Общие",
}

# ── Инициализация таблицы ─────────────────

def init_invariant_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invariants (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL DEFAULT 'general',
            title       TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ── CRUD ──────────────────────────────────

def add_invariant(category, title, description):
    conn = get_conn()
    conn.execute(
        "INSERT INTO invariants (category, title, description, created_at) VALUES (?,?,?,?)",
        (category, title, description, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def list_invariants():
    """Возвращает все инварианты: [(id, category, title, description, created_at)]"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, category, title, description, created_at FROM invariants ORDER BY category, id")
    rows = c.fetchall()
    conn.close()
    return rows


def remove_invariant(inv_id):
    conn = get_conn()
    conn.execute("DELETE FROM invariants WHERE id=?", (inv_id,))
    conn.commit()
    conn.close()


def get_invariant(inv_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, category, title, description FROM invariants WHERE id=?", (inv_id,))
    row = c.fetchone()
    conn.close()
    return row


# ── Системный промпт с инвариантами ───────

INVARIANT_SYSTEM_BLOCK = """
══════════════════════════════════════════════
⛔ ИНВАРИАНТЫ — ЖЁСТКИЕ ОГРАНИЧЕНИЯ
══════════════════════════════════════════════
Это абсолютные правила. Ты ОБЯЗАН их соблюдать.
Если пользователь просит что-то, что нарушает хотя бы один инвариант:
1. Ответь: [CONFLICT: <название инварианта>]
2. Объясни, какой инвариант нарушен и почему
3. Предложи альтернативу, которая НЕ нарушает инварианты (если возможно)
Ты НЕ можешь обойти эти правила, даже если пользователь явно просит.
══════════════════════════════════════════════

{invariants_block}

══════════════════════════════════════════════
"""

def build_invariant_prompt():
    """
    Строит блок системного промпта с инвариантами.
    Возвращает None если инвариантов нет.
    """
    rows = list_invariants()
    if not rows:
        return None

    # Группируем по категориям
    by_cat = {}
    for inv_id, cat, title, desc, _ in rows:
        by_cat.setdefault(cat, []).append((inv_id, title, desc))

    lines = []
    for cat, items in by_cat.items():
        cat_label = INVARIANT_CATEGORIES.get(cat, cat)
        lines.append(f"{cat_label}:")
        for inv_id, title, desc in items:
            lines.append(f"  [{inv_id}] {title}")
            lines.append(f"      → {desc}")
        lines.append("")

    invariants_text = "\n".join(lines).rstrip()
    return INVARIANT_SYSTEM_BLOCK.format(invariants_block=invariants_text)


# ── Детект конфликта в ответе агента ──────

def detect_conflict(answer):
    """
    Возвращает строку конфликта если агент сообщил о нарушении инварианта.
    Формат: [CONFLICT: название]
    """
    import re
    m = re.search(r'\[CONFLICT:\s*([^\]]+)\]', answer, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


# ── UI: показать список инвариантов ───────

def show_invariants():
    rows = list_invariants()
    if not rows:
        print("\n  📭 Инвариантов нет. Добавь: /inv add\n")
        return

    print(f"\n  {'─'*56}")
    print(f"  ⛔ ИНВАРИАНТЫ ({len(rows)} шт.)")
    print(f"  {'─'*56}")

    current_cat = None
    for inv_id, cat, title, desc, created in rows:
        cat_label = INVARIANT_CATEGORIES.get(cat, cat)
        if cat != current_cat:
            print(f"\n  {cat_label}")
            current_cat = cat
        print(f"  [{inv_id}] {title}")
        print(f"       {desc}")

    print(f"\n  {'─'*56}\n")


# ── UI: добавить инвариант ─────────────────

def add_invariant_interactive():
    print("\n  Добавить инвариант")
    print("  Категории:")
    cat_keys = list(INVARIANT_CATEGORIES.keys())
    for i, k in enumerate(cat_keys, 1):
        print(f"  {i}. {INVARIANT_CATEGORIES[k]}")

    ch = input("\n  Выбери категорию [1-5]: ").strip()
    try:
        cat = cat_keys[int(ch) - 1]
    except (ValueError, IndexError):
        cat = "general"

    title = input("  Название (коротко): ").strip()
    if not title:
        print("  ❌ Название обязательно.\n")
        return

    desc = input("  Описание (правило): ").strip()
    if not desc:
        print("  ❌ Описание обязательно.\n")
        return

    add_invariant(cat, title, desc)
    cat_label = INVARIANT_CATEGORIES.get(cat, cat)
    print(f"\n  ✅ Инвариант добавлен: [{cat_label}] {title}\n")


# ── UI: удалить инвариант ─────────────────

def remove_invariant_interactive():
    rows = list_invariants()
    if not rows:
        print("\n  Инвариантов нет.\n")
        return

    show_invariants()
    ch = input("  ID для удаления: ").strip()
    if ch.isdigit():
        inv_id = int(ch)
        row = get_invariant(inv_id)
        if row:
            remove_invariant(inv_id)
            print(f"\n  ✅ Инвариант [{inv_id}] '{row[2]}' удалён.\n")
        else:
            print(f"\n  ❌ Инвариант [{ch}] не найден.\n")


# ── Проверить произвольный текст ──────────

def check_text_against_invariants(text, call_api_fn):
    """
    Делает отдельный API-запрос: проверяем текст на конфликт с инвариантами.
    Используется для команды /inv check.
    """
    inv_prompt = build_invariant_prompt()
    if not inv_prompt:
        print("\n  📭 Инвариантов нет — нечего проверять.\n")
        return

    msgs = [
        {"role": "system", "content": inv_prompt},
        {"role": "system", "content": (
            "Твоя задача: проверить, нарушает ли следующий текст/предложение "
            "какой-либо из инвариантов выше. "
            "Если нарушает — начни с [CONFLICT: название инварианта] и объясни. "
            "Если не нарушает — ответь 'Конфликтов не обнаружено' и кратко объясни почему."
        )},
        {"role": "user", "content": f"Проверь: {text}"}
    ]

    print("\n  🔍 Проверяю...\n")
    r = call_api_fn(msgs)
    answer = r.get("answer", "❌ Ошибка API")

    conflict = detect_conflict(answer)
    if conflict:
        print(f"  ⛔ КОНФЛИКТ: {conflict}")
    else:
        print(f"  ✅ Конфликтов не обнаружено")

    print(f"\n  {answer}\n")
