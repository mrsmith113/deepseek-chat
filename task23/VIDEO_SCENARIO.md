# Сценарий видео — Task 23: Реранкинг и фильтрация

**Продолжительность:** ~7 минут  
**Формат:** скринкаст терминал WSL + объяснение голосом

---

## Структура видео

### 1. Вступление (30 сек)
> "День 23. В прошлый раз мы убедились что RAG работает. Сегодня делаем его умнее: добавляем фильтрацию по качеству и перефразировку запроса. Три режима, одно сравнение."

### 2. Показываем файлы (30 сек)
```bash
cd task23
ls -la
```
> "Три новых файла: reranker.py, query_rewriter.py, eval.py. Переиспользуем вопросы из task22."

### 3. Объясняем идею (1 мин)
```bash
cat reranker.py | head -20
```
> "Qdrant возвращает топ-N по cosine similarity. Но не все результаты одинаково хороши — бывает score 0.71 рядом с 0.52. Threshold filter отсекает всё ниже 0.65. MMR убирает дубли — если три чанка из одного видео, берём один лучший."

```bash
cat query_rewriter.py | head -15
```
> "Query rewriter просит Qwen3 расширить вопрос синонимами и терминами. 'Нотификация ФСБ' → 'нотификация ФСБ криптография ЕАЭС КТС уведомительный порядок'. Больше терминов — лучше recall."

### 4. Демо query_rewriter (1 мин)
```bash
~/rag-env/bin/python query_rewriter.py "Как перевести деньги в Китай?"
~/rag-env/bin/python query_rewriter.py "Что такое нотификация ФСБ?"
```
> "Смотрим как модель расширяет запрос. Это первый этап пайплайна."

### 5. Запуск eval.py (2.5 мин)
```bash
~/rag-env/bin/python eval.py
```
Пока идёт:
> "Для каждого вопроса — три прогона. Baseline без фильтра, с фильтром+MMR, с rewrite+фильтром+MMR. Смотрим как меняется keyword hit rate."

### 6. Итоги (1 мин)
```bash
~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))['summary']
print(f'Baseline:       kw={d[\"baseline\"][\"kw_avg\"]:.1%}  src={d[\"baseline\"][\"src_avg\"]:.1%}')
print(f'+filter+MMR:    kw={d[\"filter\"][\"kw_avg\"]:.1%}  src={d[\"filter\"][\"src_avg\"]:.1%}')
print(f'+rewrite:       kw={d[\"rewrite_filter\"][\"kw_avg\"]:.1%}  src={d[\"rewrite_filter\"][\"src_avg\"]:.1%}')
"
```
> "Каждый этап добавляет качество. Фильтр убирает шум. Query rewrite расширяет охват. Вместе — лучший результат."

### 7. Заключение (30 сек)
> "RAG — это пайплайн. Поиск → фильтрация → реранкинг → генерация. Каждый этап можно улучшать независимо. Следующий шаг — добавить настоящий cross-encoder reranker."

---

## Команды для съёмки (по порядку)

```bash
cd "/мnt/c/Users/Stas K/Downloads/obsidian/obsidian/10-Активные-проекты/0. Обучение БЛМ/GIT/task23"
ls -la

~/rag-env/bin/python query_rewriter.py "Как перевести деньги в Китай?"
~/rag-env/bin/python query_rewriter.py "Что такое нотификация ФСБ?"

~/rag-env/bin/python eval.py

~/rag-env/bin/python -c "
import json
d = json.load(open('eval_results.json'))['summary']
print(f'Baseline:    kw={d[\"baseline\"][\"kw_avg\"]:.1%}  src={d[\"baseline\"][\"src_avg\"]:.1%}')
print(f'+filter+MMR: kw={d[\"filter\"][\"kw_avg\"]:.1%}  src={d[\"filter\"][\"src_avg\"]:.1%}')
print(f'+rewrite:    kw={d[\"rewrite_filter\"][\"kw_avg\"]:.1%}  src={d[\"rewrite_filter\"][\"src_avg\"]:.1%}')
"
```
