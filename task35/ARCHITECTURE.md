# Архитектура AI-оркестратора ТН ВЭД

## Полная схема с паттернами курса БЛМ

```
Пользователь → Telegram сообщение
                     │
                     ▼
         ┌─────────────────────┐
         │  ROUTER (router.py) │  ← паттерн: Router
         │  route_request()    │
         └────────┬────────────┘
                  │
          ┌───────┴──────────┐
          │                  │
     CODE_LOOKUP         FULL_PIPELINE
  (код в запросе)       (стандартный путь)
          │                  │
          ▼          ┌───────┴──────────────────────────────────────────┐
   fetch_poshlin +   │              Fan-out (параллельно)               │
   fetch_fsa +       │                                                  │
   validate_eec      │  Agent1 ──── search_collections(tnved_rag)      │
   DeepSeek          │  (Sub-agent)  CTX=1400, 80к чанков              │
   ~10-15 сек        │                                                  │
                     │  Agent2 ──── search_collections(youko+baza_a)   │
                     │  (Sub-agent)  CTX=900, 50к чанков               │
                     │                                                  │
                     │  Agent3 ──── search_collections(npa_pkr_rag)    │
                     │  (Sub-agent)  CTX=3000, 26к чанков              │
                     │                                                  │
                     │  Agent4 ──── search_cross_collection(legal_cross)│
                     │  (Sub-agent)  CTX=2000, e5-large                │
                     │                                                  │
                     └──────────────────────┬───────────────────────────┘
                                            │  ~5-8 сек
                              ┌─────────────┴──────────────────┐
                              │  Chain: codes → enrichment      │
                              │                                 │
                              │  codes_all = codes1 ∪ codes3   │
                              │       │                         │
                              │  ┌────┴────────────────────┐   │
                              │  │  Параллельные инструменты│   │
                              │  │  (Tool Registry)         │   │
                              │  │                          │   │
                              │  │  fetch_poshlin_data()    │   │
                              │  │  fetch_fsa_docs()        │   │
                              │  │  fetch_tnved_for_codes() │   │
                              │  └────────────────────────── ┘  │
                              └──────────────┬──────────────────┘
                                             │ ~2-5 сек
                                             ▼
                              ┌─────────────────────────────────┐
                              │  DeepSeek (deepseek-chat)       │
                              │  T=0.1, max_tokens=5000         │
                              │  Синтез из 4 агентов            │
                              └──────────────┬──────────────────┘
                                             │ ~25-35 сек
                                             ▼
                              ┌─────────────────────────────────┐
                              │  validate_eec_codes()           │
                              │  eec_poyasnenia_rag, 21к чанков │
                              │  ✅/⚠️ официальный ТН ВЭД ЕЭК  │
                              └──────────────┬──────────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────────┐
                              │  record_request() → JSONL       │ ← метрики
                              │  latency, tokens, cost          │
                              └──────────────┬──────────────────┘
                                             │
                                             ▼
                              Ответ пользователю
                              + [🔄 Альтернативные коды] [📖 Пояснения ЕЭК]
                              (HITL: человек решает углублять ли анализ)
```

## Tool Registry (tool_registry.py)

```python
TOOL_REGISTRY = {
    "search_collections":    {dangerous: False, timeout: 25},
    "fetch_poshlin_data":    {dangerous: False, timeout: 10},
    "fetch_fsa_docs":        {dangerous: False, timeout: 8},
    "fetch_tnved_for_codes": {dangerous: False, timeout: 15},
    "validate_eec_codes":    {dangerous: False, timeout: 10},
    "get_eec_poyasnenie":    {dangerous: False, timeout: 15},
    "generate_alternatives": {dangerous: False, timeout: 60},
    # Dangerous Operations — требуют HITL:
    # /reindex eec → eec_update.sh (удаляет 21к векторов)
}
```

## Error Handling & Fallback

```python
# Каждый агент обёрнут в try/except с таймаутом
try:
    hits1, codes1 = future1.result(timeout=25)
    agents_ok += 1
except FuturesTimeout:
    log.warning("Agent1 timeout, degrading gracefully")
    hits1, codes1 = [], set()  # пайплайн продолжает с оставшимися агентами
```

Если завис 1 агент — система работает на 3-х. Если все — переходит в chat-mode.

## HITL — Dangerous Operations

```
Пользователь: /reindex eec
      │
      ▼
⚠️ ОПАСНАЯ ОПЕРАЦИЯ
Переиндексация eec_poyasnenia_rag
• Скачает 97 PDF • Создаст 21к чанков • Перезапишет коллекцию

[✅ Подтвердить]  [❌ Отмена]
      │
      ▼ (только если нажали Подтвердить)
subprocess.Popen(eec_update.sh)
```

## Метрики (metrics.py)

```
/stats →
📊 Метрики AI Pipeline — N запросов

⏱ Latency
  Total  — P50: 42.1s | P95: 68.3s | P99: 91.2s
  Агенты — P50: 6.2s  | P95: 12.4s
  LLM    — P50: 28.5s | P95: 44.1s

💰 Стоимость (DeepSeek)
  Средняя: $0.0041/запрос
  Всего: $0.123
  Токены: ~12400 prompt + 1850 completion

✅ Success Rate: 87.5%
  (agents_ok≥3 + eec_valid)

🔀 Маршруты (Router)
  FULL_PIPELINE: 28
  CODE_LOOKUP: 4
```

## Qdrant коллекции

| Коллекция | Векторов | Dim | Агент |
|-----------|----------|-----|-------|
| tnved_rag | 80 032 | 2048 | Agent1 |
| npa_pkr_rag | 26 201 | 2048 | Agent3 |
| eec_poyasnenia_rag | 21 312 | 2048 | Валидатор |
| youko_rag | 44 292 | 2048 | Agent2 |
| baza_a_rag | 5 935 | 2048 | Agent2 |
| legal_cross | ~15k | 1024 | Agent4 |
| youtube_rag | 3 255 | 2048 | — |
| sponsr_rag | 11 594 | 2048 | — |
| pkr_fts_rag | 79 | 2048 | — |
