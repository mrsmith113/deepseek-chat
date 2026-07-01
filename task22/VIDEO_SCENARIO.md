# Сценарий видео — Task 22: Первый RAG-запрос

**Продолжительность:** ~7 минут  
**Формат:** скринкаст терминал WSL + объяснение голосом  
**Терминал:** WSL (bash) — не PowerShell

---

## Структура видео

### 1. Вступление (30 сек)
> "День 22 — первый RAG-запрос. У нас уже есть база знаний: видео о ВЭД, проиндексированных в Qdrant. Сегодня сравним два подхода: модель без контекста и модель с RAG. И заодно поймаем настоящий баг прямо на камеру."

### 2. Показываем файлы (30 сек)
```bash
cd "/mnt/c/Users/Stas K/Downloads/obsidian/obsidian/10-Активные-проекты/0. Обучение БЛМ/GIT/task22"
ls -la
~/rag-env/bin/python -c "import json; [print(f'{q[\"id\"]}. {q[\"question\"]}') for q in json.load(open('questions.json'))]"
```
> "10 контрольных вопросов по ВЭД — по каждому знаем что должно быть в ответе."

### 3. Демо rag_agent.py — один вопрос в обоих режимах (1.5 мин)
```bash
~/rag-env/bin/python rag_agent.py "Что такое нотификация ФСБ?" --mode both
```

> "Без RAG — формально верно, но поверхностно. С RAG — 5 видео, score 0.76, источники [1][4][5]. Это и есть смысл RAG — не галлюцинация, а факты из базы знаний."

### 4. Запуск eval.py — первый прогон (1 мин)
```bash
~/rag-env/bin/python eval.py
```

> "Прогоняем 10 вопросов. Считаем keyword hit rate — сколько ожидаемых терминов в ответе."

Показываем результат на экране:
```
Keyword hit rate (Direct): 20.5%
Keyword hit rate (RAG):    5.0%  ⚠️ хуже
🏆 Победитель: DIRECT
```

> "Стоп. RAG проиграл? Это невозможно. Что-то сломано. Идём разбираться."

### 5. Диагностика бага (1.5 мин)
```bash
~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))
for q in d['questions']:
    print(f'Q{q[\"id\"]}: rag_answer len={len(q[\"rag_answer\"])}')
"
```

Показываем: 8 из 10 ответов пустые.

> "Вот он. rag_answer пустой у 8 вопросов из 10. RAG не проиграл — он просто не отвечал."

```bash
grep "num_predict" eval.py
```

> "num_predict: 512. Qwen3 — модель с встроенным мышлением. Она сначала думает в блоке think, потом отвечает. С RAG-контекстом (5 документов по 400 символов) мышление съедает все 512 токенов. До ответа очередь не доходит. Direct работает — контекста нет, thinking короче."

### 6. Фикс и повторный прогон (1.5 мин)
```bash
# Показываем исправленный eval.py:
# num_predict: 512 → 2048
# + /no_think в RAG-промте

~/rag-env/bin/python eval.py
```

После завершения:
```
Keyword hit rate (Direct): 20.5%
Keyword hit rate (RAG):    67%+  ✅ лучше
Source hit rate  (RAG):    80%
🏆 Победитель: RAG
```

> "Вот это другое дело. RAG работает как надо."

### 7. Итог (30 сек)
```bash
~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))
s = d['summary']
print(f'Direct: {s[\"kw_hit_direct_avg\"]:.0%} | RAG: {s[\"kw_hit_rag_avg\"]:.0%} | Sources: {s[\"source_hit_rag_avg\"]:.0%} | Победитель: {s[\"winner\"]}')
"
```

> "Урок дня: RAG — это не просто передать контекст. Нужно убедиться что модель вообще добирается до ответа. Один параметр num_predict и одна директива /no_think — и результат меняется кардинально."

---

## Команды для съёмки (по порядку)

```bash
cd "/mnt/c/Users/Stas K/Downloads/obsidian/obsidian/10-Активные-проекты/0. Обучение БЛМ/GIT/task22"

# 1. Файлы и вопросы
ls -la
~/rag-env/bin/python -c "import json; [print(f'{q[\"id\"]}. {q[\"question\"]}') for q in json.load(open('questions.json'))]"

# 2. Демо одного вопроса
~/rag-env/bin/python rag_agent.py "Что такое нотификация ФСБ?" --mode both

# 3. Первый прогон (баг)
~/rag-env/bin/python eval.py

# 4. Диагностика
~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))
for q in d['questions']:
    print(f'Q{q[\"id\"]}: rag_answer len={len(q[\"rag_answer\"])}')
"

# 5. Показать строку с багом
grep "num_predict" eval.py

# 6. Повторный прогон после фикса
~/rag-env/bin/python eval.py

# 7. Итог
~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))
s = d['summary']
print(f'Direct: {s[\"kw_hit_direct_avg\"]:.0%} | RAG: {s[\"kw_hit_rag_avg\"]:.0%} | Sources: {s[\"source_hit_rag_avg\"]:.0%} | Победитель: {s[\"winner\"]}')
"
```
