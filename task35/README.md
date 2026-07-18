# Task 35 — AI-оркестратор классификации товаров по ТН ВЭД ЕАЭС

## Реальная задача

Декларант или таможенный брокер тратит **30–60 минут** на подбор одного кода ТН ВЭД для нового товара:

1. Лезет на сайт ЕЭК — смотрит пояснения
2. Ищет предварительные классификационные решения ФТС (ПКР) — их 12 000+
3. Смотрит примеры деклараций коллег
4. Сверяется с зарубежной практикой (CBP CROSS США)
5. Проверяет ставки пошлин и требования сертификации

**Ошибка кода = доначисления + штраф до 200% от суммы пошлин (ст. 16.2 КоАП).**

Бот сокращает это до **1 запроса в Telegram (~40–60 сек)**, выдавая:
- Код с вероятностью и обоснованием
- Ссылки на конкретные ПКР/решения ЕЭК
- Ставку пошлины и НДС
- Требования сертификации (ТР ТС, нотификации ФСБ)
- Валидацию кода по официальному ТН ВЭД ЕЭК ЕАЭС

## Как AI участвует в процессе

```
Запрос пользователя → Telegram-бот
         │
         ▼ Router
   CODE_LOOKUP или FULL_PIPELINE?
         │
    FULL_PIPELINE:
         │
         ├── Agent1 (tnved_rag, 80к чанков)    ┐
         ├── Agent2 (youko+baza_a, 50к чанков)  │ Fan-out: параллельно
         ├── Agent3 (npa_pkr_rag, 26к чанков)   │ за ~5–8 сек
         └── Agent4 (legal_cross, CBP США)      ┘
                    │
         ├── fetch_poshlin_data   ┐
         ├── fetch_fsa_docs       │ Параллельные инструменты
         └── fetch_tnved_for_codes┘
                    │
         DeepSeek (deepseek-chat, T=0.1) — синтез ответа ~25–35 сек
                    │
         validate_eec_codes → блок "✅ ПРОВЕРКА ЕЭК ЕАЭС"
                    │
         Ответ пользователю + кнопки [Альтернативные коды] [Пояснения ЕЭК]
```

AI участвует на каждом шаге:
- **GigaEmbeddings** (2048d, GPU) — векторный поиск по 192k+ чанков
- **DeepSeek** — синтез ответа из 4 источников с обязательной структурой
- **Semantic fallback** — если точный поиск не нашёл, семантический всегда найдёт

## Концепции курса

| Концепция | Где реализована |
|-----------|----------------|
| LLM Agent как мини-ОС | Оркестратор управляет GPU, Qdrant, SQLite, API, сетью |
| Sub-agents | Agent1–4: у каждого свои коллекции и лимит контекста |
| Fan-out | `ThreadPoolExecutor` × 4 агента параллельно |
| Chain | Agent1+3 → коды → Agent4 (code-guided) → DeepSeek → EEC-валидатор |
| Router | `route_request()`: CODE_LOOKUP или FULL_PIPELINE |
| Tool Registry | `@register_tool` на 7 функциях, `/tools` показывает реестр |
| Dangerous Ops + HITL | `/reindex eec` → подтверждение → `subprocess.Popen(eec_update.sh)` |
| Error Handling & Fallback | `future.result(timeout=25)` → graceful degradation на 3 агентах |
| AI Pipeline | Триггер: Telegram-сообщение → полный автоматический пайплайн |
| Метрики | `record_request()` → JSONL → `/stats` (P50/P95/P99, cost, success rate) |

## Инфраструктура

- **GigaEmbeddings** `ai-sage/Giga-Embeddings-instruct` 2048d, RTX 4080 SUPER
- **Qdrant** localhost:6333, 8 коллекций, 192k+ векторов
- **SQLite fsa.db** — 4.4 млн сертификатов ФСА 2022–2026
- **DeepSeek API** — deepseek-chat, $0.27/1M prompt + $1.10/1M completion
- **Telegram** через V2Ray proxy (10808)

## Файлы

```
rag-agent/
├── orchestrator_tg_bot.py  # главный файл оркестратора (1200+ строк)
├── tool_registry.py        # Tool Registry + Executor с метриками
├── router.py               # Router pattern: CODE_LOOKUP / FULL_PIPELINE
├── metrics.py              # Latency P50/P95/P99, Cost, Success Rate
├── eec_loader.py           # загрузчик ЕЭК ТН ВЭД (скачка/парсинг/Qdrant)
├── eec_update.sh           # крон-скрипт ежемесячного обновления
├── fsa.db                  # SQLite 4.4M сертификатов
└── cross.db                # SQLite индекс CBP CROSS

task35/
├── README.md               # этот файл
├── ARCHITECTURE.md         # полная архитектурная схема
├── tool_registry.py        # копия
├── router.py               # копия
├── metrics.py              # копия
└── eval/
    ├── golden_set.md       # 10 товаров с эталонными кодами
    └── results.md          # качество: 1-10 по каждому
```
