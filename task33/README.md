# task33 — Ассистент поддержки пользователей

День 33 курса БЛМ. Ассистент первой линии поддержки «Юко-Кабинета»: берёт
вопрос клиента, поднимает по CRM карточку тикета и клиента, ищет ответ в базе
знаний (RAG) и выдаёт готовый ответ инженера — **диагноз · шаги решения · что
уточнить у клиента**. Работает офлайн, без единой внешней зависимости.

## Как это работает

```
вопрос ──▶ support.py (CLI)
              │
              ├──▶ crm_tools ──▶ data/crm.json     тикет → клиент:
              │                                    тариф, роль, SSO, домен, 2FA,
              │                                    статус, код ошибки, переписка
              │                                            │
              ├──▶ RAG: chunking → indexer → search        │
              │         (docs/*.md, TF-IDF)                │
              │              │                             │
              │              ▼                             ▼
              └──▶ assistant.answer() ──── контекст + топ-4 чанка
                             │
                             ├─ gen_deepseek()  DEEPSEEK_API_KEY ─┐
                             ├─ gen_ollama()    localhost:11434 ──┤ каскад
                             └─ gen_offline()   правила + RAG ────┘ (не падает)
                             │
                             ▼
                    ответ + «Источники: …» + «Контекст: …»

mcp_crm_server.py ──▶ те же crm_tools как MCP-инструменты для Claude Desktop/Code
```

## Модули (одна ответственность на модуль)

- **crm_tools.py** — доступ к `data/crm.json`: `load_crm`, `get_user`,
  `get_ticket`, `user_tickets`, `search_tickets` + человекочитаемые
  `format_user` / `format_ticket`. Только данные, ни RAG, ни LLM.
- **mcp_crm_server.py** — MCP-сервер (JSON-RPC over stdio, чистый stdlib):
  `initialize` / `tools/list` / `tools/call`. Инструменты: `crm_user`,
  `crm_ticket`, `crm_user_tickets`, `crm_search`.
- **chunking.py** — режет `docs/*.md` по секциям (## / ###).
  Заголовок секции кладётся в текст чанка (иначе он невидим для поиска),
  чанки-«обложки» без тела отбрасываются.
- **search.py** — retrieval: TF-IDF на stdlib + косинус. Опциональный
  dense-бэкенд на sentence-transformers (`EMB_BACKEND=dense`).
- **indexer.py** — `build_index()` / `load_index()` → `index.json`, без внешней БД.
- **assistant.py** — ядро: CRM-контекст + RAG + LLM-каскад → ответ.
- **support.py** — CLI-точка входа.

## Запуск (офлайн, одной командой)

```bash
bash run.sh
```

Или вручную:

```bash
python3 indexer.py                                    # собрать RAG-индекс
python3 support.py --ticket T-1042 --question "Почему не работает авторизация?"
python3 support.py --user U-104 --question "Как получить API-ключ?"
python3 support.py --question "Как выгрузить документы?"   # чистый RAG
python3 support.py --demo                             # 3 показательных кейса
python3 support.py --ticket T-1042 -q "..." --out answer.md
```

Каждый модуль умеет самопроверку: `python3 crm_tools.py`, `python3 search.py` и т.д.

## LLM (опционально)

- `DEEPSEEK_API_KEY` — генерация через DeepSeek (`deepseek-chat`).
- Иначе пробуется Ollama (`OLLAMA_MODEL`, по умолч. `qwen3:14b`) на :11434.
- Нет ни того, ни другого — отвечает офлайн-ветка: правила по CRM-данным +
  топ-чанк базы знаний. **Ответ содержательный в любом случае**, и в подвале
  всегда видно, какой генератор сработал (`deepseek` / `ollama` / `offline`).

## MCP-сервер в Claude Desktop / Claude Code

`claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`,
Windows: `%APPDATA%\Claude\`) либо `.mcp.json` в проекте для Claude Code:

```json
{
  "mcpServers": {
    "support-assistant-crm": {
      "command": "python3",
      "args": ["/absolute/path/to/task33/mcp_crm_server.py"]
    }
  }
}
```

Проверка сервера вручную:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"crm_ticket","arguments":{"ticket_id":"T-1042"}}}' | python3 mcp_crm_server.py
```

## Пример вывода

```
# Ответ поддержки — T-1042

**Вопрос:** Почему не работает авторизация?

**Диагноз.** Игорь, SSO не активен: домен компании не верифицирован. SAML-вход
остаётся выключенным, пока в DNS домена example-import.ru не подтверждена
TXT-запись. Именно поэтому вход через SSO не проходит (код ошибки SSO-003).

**Шаги решения:**
1. Временно входите по логину и паролю — этот способ работает, SSO его не блокирует.
2. Откройте «Настройки» → «Домены компании» и скопируйте выданное значение TXT-записи.
3. Добавьте TXT-запись в DNS домена у вашего регистратора.
4. Дождитесь распространения DNS (15–60 минут) и нажмите «Проверить домен».
5. После верификации флаг domain_verified станет true — SSO заработает автоматически.
6. Если ошибка осталась — сверьте ACS URL и Entity ID в SAML-провайдере.

**Что уточнить у клиента:**
- У кого доступ к DNS домена — у вас или у подрядчика?
- Какой SAML-провайдер используете (Keycloak, Okta, ADFS, другой)?
- Скриншот ошибки на странице входа — что видит пользователь?

---
Источники: troubleshooting.md :: SSO-003 — домен не верифицирован; faq.md :: 1. Почему не работает авторизация...
Контекст: тикет T-1042 (open, код SSO-003), клиент Игорь Башев (ООО ЭлектроИмпорт), тариф Enterprise
Генератор: offline · RAG-бэкенд: tfidf (38 чанков, найдено 4)
```

## Данные

- `docs/product.md`, `docs/faq.md`, `docs/troubleshooting.md` — база знаний для RAG.
- `data/crm.json` — 6 клиентов и 8 тикетов (`users` + `tickets`).

## Зависимости

Нет. Только стандартная библиотека Python 3.10+.
