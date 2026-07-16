"""Ядро ассистента поддержки: вопрос + CRM-контекст + RAG → ответ инженера.

Пайплайн:
  1. CRM (crm_tools)   — тянем тикет и/или пользователя: тариф, роль, флаги
                         SSO/домен/2FA, статус, код ошибки, переписка;
  2. RAG (search)      — по вопросу + теме тикета + коду ошибки + области
                         продукта достаём топ-4 чанка базы знаний;
  3. LLM-каскад        — DeepSeek API → Ollama → офлайн-ветка (правила + RAG);
  4. render            — диагноз → шаги → что уточнить + источники и контекст.

Ключевая идея: ответ содержателен ВСЕГДА. LLM — усилитель, а не опора:
офлайн-ветка собирает ответ детерминированно из правил по CRM-данным и
найденных чанков. Ни сети, ни ключа для этого не нужно.
"""
from __future__ import annotations

import json
import os
import urllib.request

import crm_tools
from indexer import load_index
from search import build_backend

RAG_MIN_SCORE = 0.02  # ниже этого чанк считаем шумом
RAG_TOP_K = 4


# ------------------------------------------------------------ CRM-контекст --
def resolve_context(ticket_id: str | None,
                    user_id: str | None) -> tuple[dict | None, dict | None]:
    """По ticket_id/user_id достаёт тикет и пользователя.

    Если задан тикет — пользователь берётся из его поля user_id.
    Если задан только user_id — тикета нет (общий вопрос от клиента).
    """
    if not ticket_id and not user_id:
        return None, None

    crm = crm_tools.load_crm()
    ticket = None
    if ticket_id:
        ticket = crm_tools.get_ticket(ticket_id, crm)
        user_id = ticket.get("user_id") or user_id
    user = crm_tools.get_user(user_id, crm) if user_id else None
    return ticket, user


def format_context(ticket: dict | None, user: dict | None) -> str:
    """Контекст клиента/тикета одним блоком — и для LLM, и для офлайн-ветки."""
    if not ticket and not user:
        return "(контекст клиента не задан — общий вопрос без тикета)"
    parts = []
    if user:
        parts.append(crm_tools.format_user(user))
    if ticket:
        parts.append(crm_tools.format_ticket(ticket))
    return "\n\n".join(parts)


# ------------------------------------------------------------------- RAG -----
def build_query(question: str, ticket: dict | None) -> str:
    """Запрос к базе знаний = вопрос + тема тикета + код ошибки + область."""
    bits = [question or ""]
    if ticket:
        bits += [str(ticket.get("subject") or ""),
                 str(ticket.get("error_code") or ""),
                 str(ticket.get("product_area") or "")]
        for m in (ticket.get("messages") or [])[:2]:
            bits.append(str(m.get("text") or "")[:200])
    return "\n".join(b for b in bits if b.strip())


def retrieve(question: str, ticket: dict | None,
             k: int = RAG_TOP_K) -> tuple[list[tuple[float, dict]], object]:
    """Топ-K релевантных чанков базы знаний (с отсечкой по score)."""
    backend = build_backend(load_index())
    hits = backend.search(build_query(question, ticket), k=k)
    return [(s, c) for s, c in hits if s >= RAG_MIN_SCORE], backend


def format_rag(hits: list[tuple[float, dict]]) -> str:
    """Найденные чанки текстом, с указанием источника (файл :: секция)."""
    if not hits:
        return "(релевантных статей в базе знаний не найдено)"
    out = []
    for score, ch in hits:
        out.append(f"### [{score:.2f}] {ch['source']} :: {ch['section']}\n"
                   f"{ch['text'][:900]}")
    return "\n\n".join(out)


def sources_line(hits: list[tuple[float, dict]]) -> str:
    """Строка «Источники: …» — файлы и секции, на которые опирался ответ."""
    if not hits:
        return "Источники: база знаний не дала релевантных статей."
    seen, refs = set(), []
    for _, ch in hits:
        ref = f"{ch['source']} :: {ch['section']}"
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return "Источники: " + "; ".join(refs)


# --------------------------------------------------------------- LLM-каскад --
def _prompt(question: str, ctx: str, rag: str, user: dict | None) -> str:
    name = (user or {}).get("name", "клиент")
    return (
        "Ты — инженер поддержки «Юко-Кабинета» (SaaS для ВЭД-импортёров).\n"
        "Отвечай на русском языке. Опирайся ТОЛЬКО на данные тикета/клиента и "
        "контекст из базы знаний ниже. Ничего не выдумывай: если данных не "
        "хватает — так и напиши и вынеси вопрос в раздел уточнений.\n"
        f"Обращайся к клиенту по имени: {name}.\n\n"
        "Формат ответа строго такой:\n"
        "**Диагноз.** Одно-два предложения: в чём причина. Если из флагов "
        "клиента видно конкретную причину (например, SSO включён, но домен не "
        "верифицирован) — назови её прямо.\n"
        "**Шаги решения:** нумерованный список конкретных действий.\n"
        "**Что уточнить у клиента:** маркированный список вопросов.\n\n"
        f"=== ВОПРОС ===\n{question}\n\n"
        f"=== КОНТЕКСТ КЛИЕНТА И ТИКЕТА (CRM) ===\n{ctx}\n\n"
        f"=== БАЗА ЗНАНИЙ (RAG) ===\n{rag[:3000]}\n\n=== ОТВЕТ ===")


def gen_deepseek(prompt: str) -> str | None:
    """Генерация через DeepSeek API. Нет ключа/сети — None, без исключений."""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        return None
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.2}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[deepseek недоступен: {e}]")
        return None


def gen_ollama(prompt: str) -> str | None:
    """Генерация через локальную Ollama. Не поднята — None, без исключений."""
    body = json.dumps({"model": os.getenv("OLLAMA_MODEL", "qwen3:14b"),
                       "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("response", "").strip() or None
    except Exception:
        return None


# ----------------------------------------------------------- офлайн-ветка ----
_AUTH_WORDS = ("авториз", "вход", "войти", "логин", "login", "sso", "saml",
               "пароль", "аутентиф", "2fa", "двухфактор")
_API_WORDS = ("api", "апи", "ключ", "токен", "интеграц", "вебхук", "webhook",
              "rate limit", "429")


def _topic(question: str, ticket: dict | None) -> str:
    """Грубая тематика обращения: auth / api / other (по тексту и тикету)."""
    blob = (question or "").lower()
    if ticket:
        # error_code может быть null — везде страхуемся через `or ""`
        blob += " " + str(ticket.get("subject") or "").lower()
        blob += " " + str(ticket.get("product_area") or "").lower()
        blob += " " + str(ticket.get("error_code") or "").lower()
    if any(w in blob for w in _AUTH_WORDS):
        return "auth"
    if any(w in blob for w in _API_WORDS):
        return "api"
    return "other"


def _domain_of(user: dict | None) -> str:
    """Домен компании клиента — из email. Именно его верифицируют в DNS."""
    email = (user or {}).get("email") or ""
    if "@" in email:
        return email.rsplit("@", 1)[1]
    return "домен вашей компании"


def offline_rules(question: str, ticket: dict | None,
                  user: dict | None) -> tuple[str, list[str], list[str]] | None:
    """Детерминированные правила по CRM-данным → (диагноз, шаги, уточнения).

    Правила бьют точнее RAG, потому что видят флаги конкретного клиента.
    None — правило не сработало, значит ответ соберём из чанков базы знаний.
    """
    topic = _topic(question, ticket)
    plan = (user or {}).get("plan")
    err = str((ticket or {}).get("error_code") or "").upper()
    domain = _domain_of(user)

    # 1. SSO включён, но домен не верифицирован — классика тикета T-1042.
    if (user and user.get("sso_enabled") is True
            and user.get("domain_verified") is False
            and topic == "auth"):
        return (
            "SSO не активен: домен компании не верифицирован. SAML-вход "
            "остаётся выключенным, пока в DNS домена "
            f"{domain} не подтверждена TXT-запись. "
            "Именно поэтому вход через SSO не проходит"
            + (f" (код ошибки {err})." if err else "."),
            ["Временно входите по логину и паролю — этот способ работает, "
             "SSO его не блокирует.",
             "Откройте «Настройки» → «Домены компании» и скопируйте выданное "
             "значение TXT-записи.",
             "Добавьте TXT-запись в DNS домена у вашего регистратора "
             "(тип TXT, имя @ или указанный в кабинете хост).",
             "Дождитесь распространения DNS (обычно 15–60 минут, "
             "иногда до 24 часов) и нажмите «Проверить домен» в кабинете.",
             "После успешной верификации флаг domain_verified станет true — "
             "кнопка «Войти через SSO» заработает автоматически.",
             "Если после верификации ошибка осталась — сверьте в SAML-провайдере "
             "ACS URL и Entity ID из раздела «Интеграции» → SSO."],
            ["У кого доступ к DNS домена — у вас или у подрядчика?",
             "Какой SAML-провайдер используете (Keycloak, Okta, ADFS, другой)?",
             "Скриншот ошибки на странице входа — что видит пользователь?"])

    # 2. Free + вопрос про API: API-ключей на этом тарифе просто нет.
    if plan == "Free" and topic == "api":
        return (
            "На тарифе Free API-ключи недоступны — это ограничение тарифа, "
            "а не сбой. Ключи открываются с тарифа Pro.",
            ["Перейдите на тариф Pro в разделе «Биллинг» — станет доступно "
             "до 5 API-ключей и rate limit 60 req/min.",
             "После смены тарифа откройте «Интеграции» → «API-ключи» → "
             "«Создать ключ».",
             "Сохраните ключ сразу: в кабинете он показывается один раз.",
             "Если нужен только разовый экспорт данных — можно обойтись "
             "выгрузкой из раздела «Документы» без API."],
            ["Какая задача решается через API — интеграция с 1С, обмен "
             "статусами, что-то другое?",
             "Какой ожидаемый объём запросов в минуту?"])

    # 3. AUTH-005 — временная блокировка после неудачных попыток.
    if err == "AUTH-005":
        return (
            "AUTH-005 — аккаунт временно заблокирован после серии неудачных "
            "попыток входа. Это защита от перебора, блокировка снимается сама "
            "через 15 минут.",
            ["Подождите 15 минут с момента последней попытки — "
             "блокировка снимется автоматически.",
             "Не пытайтесь входить в это время: каждая новая попытка "
             "перезапускает отсчёт.",
             "Сбросьте пароль через «Забыли пароль» — так вы точно исключите "
             "ошибку в пароле.",
             "Если включена 2FA — проверьте, что время на телефоне "
             "синхронизировано, иначе TOTP-коды не подойдут."],
            ["Сколько человек в компании ловят эту ошибку — один или все?",
             "Не менялся ли пароль недавно (в том числе автозаполнением "
             "браузера)?"])

    # 4. API-429 — превышен rate limit тарифа.
    if err == "API-429" or (topic == "api" and "429" in (question or "")):
        limit = {"Pro": "60 req/min", "Enterprise": "600 req/min"}.get(
            plan or "", "лимит вашего тарифа")
        return (
            f"API-429 — превышен rate limit API ({limit}). Сервер не сломан: "
            "он намеренно отбивает запросы сверх квоты.",
            ["Посмотрите заголовок Retry-After в ответе 429 — в нём число "
             "секунд до следующей попытки.",
             "Добавьте в клиент экспоненциальный backoff с джиттером "
             "вместо повторов в цикле.",
             "Разнесите массовые операции во времени или уложите их "
             "в батч-запросы вместо поштучных.",
             "Если нагрузка легитимно выше квоты — обсудите повышение лимита "
             "или переход на Enterprise (600 req/min)."],
            ["Какой примерно RPS шлёт интеграция в пике?",
             "Запросы идут из одного процесса или параллельно из нескольких?"])

    return None


def _after_name(text: str) -> str:
    """Опускает заглавную после обращения («Ольга, похоже…»).

    Аббревиатуры не трогаем: «SSO не активен», «API-429» должны остаться как есть.
    """
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def gen_offline(question: str, ticket: dict | None, user: dict | None,
                hits: list[tuple[float, dict]]) -> str:
    """Ответ без LLM: правила по CRM + топ-чанк базы знаний. Не падает никогда."""
    name = (user or {}).get("name", "").split()[0] if user else ""
    hello = f"{name}, " if name else ""

    ruled = offline_rules(question, ticket, user)
    if ruled:
        diagnosis, steps, asks = ruled
    elif hits:
        # Преамбула документа («intro») — это оглавление, а не ответ:
        # берём лучший содержательный чанк, если он есть.
        top = next((c for _, c in hits if c["section"] != "intro"), hits[0][1])
        # В тексте чанка первой строкой лежит заголовок секции (мы кладём его
        # туда ради поиска) — в ответе он лишний: секция уже названа в диагнозе.
        text = top["text"]
        if text.startswith(top["section"]):
            text = text[len(top["section"]):]
        snippet = " ".join(text.split())[:700]
        diagnosis = (f"Похоже, ваш вопрос закрывается статьёй базы знаний "
                     f"«{top['section']}» ({top['source']}).")
        steps = [snippet]
        asks = ["Опишите, что именно вы делаете и что видите на экране "
                "(шаги + текст ошибки).",
                "В каком разделе кабинета возникает проблема?"]
    else:
        diagnosis = ("По вашему вопросу в базе знаний не нашлось точного "
                     "совпадения — нужны детали, чтобы не гадать.")
        steps = ["Опишите проблему пошагово: что нажимаете и что происходит.",
                 "Приложите точный текст ошибки или её код (вида SSO-003).",
                 "Укажите раздел кабинета и время инцидента — "
                 "поднимем логи по вашей компании."]
        asks = ["Проблема воспроизводится у всех сотрудников или у одного?",
                "Когда всё работало в последний раз?"]

    if hello:
        diagnosis = _after_name(diagnosis)
    out = [f"**Диагноз.** {hello}{diagnosis}", "", "**Шаги решения:**"]
    out += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    out += ["", "**Что уточнить у клиента:**"]
    out += [f"- {a}" for a in asks]
    return "\n".join(out)


# ---------------------------------------------------------------- пайплайн ---
def answer(question: str, ticket_id: str | None = None,
           user_id: str | None = None, use_llm: bool = True) -> str:
    """Главная функция: вопрос (+тикет/клиент) → готовый ответ поддержки."""
    if not (question or "").strip():
        raise ValueError("Пустой вопрос — нечего отвечать")

    ticket, user = resolve_context(ticket_id, user_id)
    ctx = format_context(ticket, user)
    hits, backend = retrieve(question, ticket)
    rag = format_rag(hits)

    body, gen = None, "offline"
    if use_llm:
        prompt = _prompt(question, ctx, rag, user)
        text = gen_deepseek(prompt)
        if text:
            body, gen = text, "deepseek"
        else:
            text = gen_ollama(prompt)
            if text:
                body, gen = text, "ollama"
    if body is None:
        body = gen_offline(question, ticket, user, hits)

    # шапка
    head = [f"# Ответ поддержки — {ticket['id']}" if ticket
            else "# Ответ поддержки", "",
            f"**Вопрос:** {question}", "", ""]

    # подвал: источники + контекст + кто генерировал
    ctx_bits = []
    if ticket:
        ctx_bits.append(f"тикет {ticket['id']} ({ticket.get('status', '—')}, "
                        f"код {ticket.get('error_code') or '—'})")
    if user:
        ctx_bits.append(f"клиент {user.get('name')} "
                        f"({user.get('company', '—')})")
        ctx_bits.append(f"тариф {user.get('plan', '—')}")
    ctx_line = ("Контекст: " + ", ".join(ctx_bits)) if ctx_bits \
        else "Контекст: без тикета и клиента (общий вопрос)"

    foot = ["", "", "---", sources_line(hits), ctx_line,
            f"Генератор: {gen} · RAG-бэкенд: {backend.name} "
            f"({len(backend.chunks)} чанков, найдено {len(hits)})"]
    return "\n".join(head) + body + "\n".join(foot)


if __name__ == "__main__":
    print(answer("Почему не работает авторизация?", ticket_id="T-1042"))
