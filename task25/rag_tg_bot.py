#!/usr/bin/env python3
"""
rag_tg_bot.py — Telegram RAG-чат с памятью задачи.
Бот: @Deepseek_youko_bot
База: tnved_rag (Qdrant, GigaEmbeddings)
Модель: DeepSeek API

Команды:
  /start   — приветствие
  /clear   — сбросить историю и память
  /memory  — показать текущую память задачи
  <любой текст> → RAG-поиск + ответ с источниками

Запуск:
  python3 /home/stashome/rag-agent/rag_tg_bot.py

Сервис:
  systemctl --user start rag-tg-bot
"""

import os, requests, time, logging, sys, re, json, torch
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
TG_TOKEN     = os.environ["TG_TOKEN"]
TG_API       = f"https://api.telegram.org/bot{TG_TOKEN}"
PROXIES      = {"https": "http://127.0.0.1:10808", "http": "http://127.0.0.1:10808"}

DEEPSEEK_KEY = os.environ["DEEPSEEK_KEY"]
MODEL_NAME   = "ai-sage/Giga-Embeddings-instruct"
COLLECTIONS  = ["tnved_rag", "youko_rag"]   # все базы для поиска
QDRANT_URL   = "http://localhost:6333"
TOP_K        = 5   # топ из КАЖДОЙ коллекции, потом объединяем и берём лучшие TOP_K
MAX_HISTORY  = 10
RAG_MIN_SCORE = 0.5
LOG_FILE     = "/home/stashome/rag-agent/rag_tg_bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Инициализация ─────────────────────────────────────────────────────────────
log.info("Загружаю GigaEmbeddings...")
device = "cuda" if torch.cuda.is_available() else "cpu"
embed_model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=device)
log.info(f"Модель загружена на {device}")

qdrant = QdrantClient(url=QDRANT_URL)
ds = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")

# ── Состояние чатов ───────────────────────────────────────────────────────────
# chat_state[chat_id] = {
#   "history": [{"role": "user"/"assistant", "content": "..."}],
#   "task_memory": {
#     "goal": str,          # цель диалога
#     "terms": [],          # зафиксированные термины/ограничения
#     "clarified": [],      # что уже уточнено
#   }
# }
chat_state = defaultdict(lambda: {
    "history": [],
    "task_memory": {"goal": "", "terms": [], "clarified": []},
})

# ── Telegram API ──────────────────────────────────────────────────────────────
def tg_get(path, **params):
    r = requests.get(f"{TG_API}/{path}", params=params, proxies=PROXIES, timeout=35)
    return r.json()

def tg_send(chat_id, text, parse_mode="Markdown") -> int | None:
    chunks = _split(text, 4000)
    msg_id = None
    for chunk in chunks:
        r = requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": chunk, "parse_mode": parse_mode,
        }, proxies=PROXIES, timeout=15)
        data = r.json()
        if data.get("ok") and not msg_id:
            msg_id = data["result"]["message_id"]
    return msg_id

def tg_edit(chat_id, message_id, text, parse_mode="Markdown") -> bool:
    """Редактирует сообщение. При ошибке Markdown пробует без parse_mode."""
    for pm in [parse_mode, ""]:
        r = requests.post(f"{TG_API}/editMessageText", json={
            "chat_id": chat_id, "message_id": message_id,
            "text": text[:4096], "parse_mode": pm,
        }, proxies=PROXIES, timeout=15)
        data = r.json()
        if data.get("ok"):
            return True
        log.warning(f"tg_edit failed (parse_mode={pm!r}): {data.get('description')}")
        if "parse" not in (data.get("description") or "").lower():
            break  # не Markdown-ошибка, не пробуем без pm
    return False

def tg_action(chat_id, action="typing"):
    requests.post(f"{TG_API}/sendChatAction",
                  json={"chat_id": chat_id, "action": action},
                  proxies=PROXIES, timeout=5)

def _split(text, size):
    return [text[i:i+size] for i in range(0, len(text), size)]

# ── RAG ───────────────────────────────────────────────────────────────────────
def _source_label(raw: str, collection: str = "") -> str:
    s = raw.lower()
    # youko_rag источники
    if collection == "youko_rag" or "youko" in collection:
        if s == "npa":
            return "НПА Юко"
        if s == "articles":
            return "Статьи Юко"
        if s == "youtube":
            return "YouTube Юко"
        return "База Юко"
    # tnved_rag источники
    if "pkr" in s:
        return "ПКР ЕАЭС"
    if "eec" in s or "еэк" in s:
        return "ЕЭК"
    return "База ТН ВЭД"

def search_rag(query: str, top_k: int = TOP_K) -> list[dict]:
    vec = embed_model.encode(
        [f"Запрос: {query}"], normalize_embeddings=True, convert_to_numpy=True
    )[0].tolist()

    all_hits = []
    active_collections = [c.name for c in qdrant.get_collections().collections]

    for col in COLLECTIONS:
        if col not in active_collections:
            continue
        try:
            response = qdrant.query_points(
                collection_name=col,
                query=vec,
                limit=top_k,
                with_payload=True,
            )
            for h in response.points:
                p = h.payload or {}
                src_raw = p.get("source", p.get("file", "—"))
                all_hits.append({
                    "score": round(h.score, 3),
                    "text": p.get("text", ""),
                    "source": _source_label(src_raw, col),
                    "heading": p.get("heading", ""),
                    "collection": col,
                })
        except Exception as e:
            log.warning(f"search in {col} failed: {e}")

    # Сортируем по score и берём топ TOP_K
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:top_k]

# ── Память задачи ─────────────────────────────────────────────────────────────
def update_task_memory(state: dict, user_msg: str, assistant_msg: str):
    """DeepSeek извлекает обновления для памяти задачи."""
    mem = state["task_memory"]
    # Не вызываем каждый раз — только каждые 3 сообщения
    if len(state["history"]) % 3 != 0:
        return

    prompt = f"""Ты анализируешь диалог и обновляешь структурированную память задачи.

Текущая память:
- Цель: {mem['goal'] or 'не определена'}
- Зафиксированные термины/ограничения: {', '.join(mem['terms']) or 'нет'}
- Что уточнено: {', '.join(mem['clarified']) or 'нет'}

Новое сообщение пользователя: {user_msg}
Ответ ассистента: {assistant_msg[:300]}

Верни JSON с обновлёнными полями (только то что изменилось):
{{"goal": "...", "new_terms": ["..."], "new_clarified": ["..."]}}

Если ничего не изменилось — верни пустой JSON {{}}"""

    try:
        resp = ds.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        # Извлекаем JSON
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            if data.get("goal"):
                mem["goal"] = data["goal"]
            if data.get("new_terms"):
                for t in data["new_terms"]:
                    if t not in mem["terms"]:
                        mem["terms"].append(t)
            if data.get("new_clarified"):
                for c in data["new_clarified"]:
                    if c not in mem["clarified"]:
                        mem["clarified"].append(c)
    except Exception as e:
        log.warning(f"task_memory update failed: {e}")

# ── Генерация ответа (с прогрессом через edit) ───────────────────────────────
def generate_answer(chat_id: int, user_msg: str, status_msg_id: int | None = None) -> str:
    state = chat_state[chat_id]
    mem = state["task_memory"]

    # Этап 1: RAG-поиск
    if status_msg_id:
        tg_edit(chat_id, status_msg_id, "🔍 Ищу в базе знаний...")
    hits = search_rag(user_msg)

    # Авто-режим: если лучший результат ниже порога — чат без RAG
    best_score = hits[0]["score"] if hits else 0
    use_rag = best_score >= RAG_MIN_SCORE

    context_parts = []
    sources = []
    if use_rag:
        for i, h in enumerate(hits, 1):
            if h["text"]:
                context_parts.append(f"[{i}] {h['text'][:500]}")
                sources.append(f"{i}. {_source_label(h['source'])} (релевантность: {h['score']})")

    found_count = len(context_parts)

    # Этап 2: генерация
    if status_msg_id:
        if use_rag:
            tg_edit(chat_id, status_msg_id, f"✍️ Нашёл {found_count} фрагментов, пишу ответ...")
        else:
            tg_edit(chat_id, status_msg_id, "✍️ Пишу ответ...")

    memory_block = ""
    if mem["goal"] or mem["terms"] or mem["clarified"]:
        memory_block = "\n\nПАМЯТЬ ЗАДАЧИ:"
        if mem["goal"]:
            memory_block += f"\n- Цель пользователя: {mem['goal']}"
        if mem["terms"]:
            memory_block += f"\n- Зафиксированные термины: {', '.join(mem['terms'])}"
        if mem["clarified"]:
            memory_block += f"\n- Уже уточнено: {', '.join(mem['clarified'])}"

    if use_rag:
        context = "\n\n".join(context_parts)
        system_prompt = f"""Ты — эксперт по ТН ВЭД, таможенному праву и ВЭД в России.
Отвечай чётко и по делу, используя предоставленный контекст.
Всегда указывай номера источников [1], [2] и т.д. в тексте ответа.{memory_block}

КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:
{context}"""
    else:
        system_prompt = f"""Ты — дружелюбный ассистент по ВЭД, таможне и ТН ВЭД.
Отвечай кратко и по существу.{memory_block}"""
        log.info(f"[{chat_id}] auto-mode: chat (score={best_score:.3f} < {RAG_MIN_SCORE})")

    messages = [{"role": "system", "content": system_prompt}]
    messages += state["history"][-MAX_HISTORY:]
    messages.append({"role": "user", "content": user_msg})

    resp = ds.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.3,
        max_tokens=1000,
    )
    answer = resp.choices[0].message.content.strip()

    if use_rag and sources:
        answer += "\n\n📚 *Источники:*\n" + "\n".join(sources)

    state["history"].append({"role": "user", "content": user_msg})
    state["history"].append({"role": "assistant", "content": answer})
    if len(state["history"]) > MAX_HISTORY * 2:
        state["history"] = state["history"][-MAX_HISTORY * 2:]

    update_task_memory(state, user_msg, answer)

    return answer

# ── Обработчики команд ────────────────────────────────────────────────────────
def cmd_start(chat_id):
    tg_send(chat_id,
        "👋 *RAG-чат по ВЭД, ТН ВЭД и таможне*\n\n"
        "Ищу ответы в двух базах:\n"
        "• *База ТН ВЭД* — 114 717 документов (ifcg, ПКР ЕАЭС, ЕЭК)\n"
        "• *База знаний Юко* — НПА, статьи сайта, YouTube-транскрипты\n\n"
        "Помню контекст диалога и цель запроса.\n\n"
        "Команды:\n"
        "/clear — сбросить историю\n"
        "/memory — показать память задачи"
    )

def cmd_clear(chat_id):
    chat_state[chat_id] = {
        "history": [],
        "task_memory": {"goal": "", "terms": [], "clarified": []},
    }
    tg_send(chat_id, "🗑 История и память задачи сброшены.")

def cmd_memory(chat_id):
    mem = chat_state[chat_id]["task_memory"]
    hist_len = len(chat_state[chat_id]["history"]) // 2
    text = f"🧠 *Память задачи*\n\n"
    text += f"*Цель:* {mem['goal'] or 'не определена'}\n"
    text += f"*Термины:* {', '.join(mem['terms']) or 'нет'}\n"
    text += f"*Уточнено:* {', '.join(mem['clarified']) or 'нет'}\n"
    text += f"\n*Сообщений в истории:* {hist_len}"
    tg_send(chat_id, text)

# ── Главный цикл ──────────────────────────────────────────────────────────────
def process_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return

    log.info(f"[{chat_id}] {text[:80]}")

    if text.startswith("/start"):
        cmd_start(chat_id)
    elif text.startswith("/clear"):
        cmd_clear(chat_id)
    elif text.startswith("/memory"):
        cmd_memory(chat_id)
    else:
        try:
            status_id = tg_send(chat_id, "🔍 Ищу в базе знаний...", parse_mode="")
            answer = generate_answer(chat_id, text, status_msg_id=status_id)
            edited = tg_edit(chat_id, status_id, answer) if status_id else False
            if not edited:
                tg_send(chat_id, answer)
            # Если ответ длиннее 4096 — шлём остаток отдельно
            if len(answer) > 4096:
                for chunk in _split(answer[4096:], 4000):
                    tg_send(chat_id, chunk)
        except Exception as e:
            log.error(f"generate_answer error: {e}", exc_info=True)
            tg_send(chat_id, f"❌ Ошибка: {e}")

def main():
    log.info("RAG TG Bot starting...")
    me = tg_get("getMe").get("result", {})
    log.info(f"Bot: @{me.get('username')} ({me.get('first_name')})")

    offset = None
    log.info("Polling...")
    while True:
        try:
            params = {"timeout": 30, "limit": 10}
            if offset:
                params["allowed_updates"] = ["message"]
                params["offset"] = offset
            data = tg_get("getUpdates", **params)
            updates = data.get("result", [])
            for upd in updates:
                try:
                    process_update(upd)
                except Exception as e:
                    log.error(f"Update error: {e}", exc_info=True)
                offset = upd["update_id"] + 1
        except KeyboardInterrupt:
            log.info("Stopped.")
            break
        except Exception as e:
            log.error(f"Polling error: {e}", exc_info=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
