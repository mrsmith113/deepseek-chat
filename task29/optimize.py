#!/usr/bin/env python3
"""
Task 29 — Оптимизация параметров локальной LLM
Перебирает комбинации: temperature, max_tokens, repeat_penalty, prompt_template
Для каждой комбинации: время ответа + оценка качества 1-5
Выводит топ-3 конфигурации.
"""

import time
import json
import sys
import requests
import statistics
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "../task28")
from rag_local import retrieve

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:14b"

_http = requests.Session()
_http.trust_env = False

# ── Тестовые вопросы ──────────────────────────────────────────────────────────
TEST_QUESTIONS = [
    "Что такое нотификация ФСБ?",
    "Как рассчитать таможенную пошлину?",
    "Какие документы нужны для параллельного импорта?",
]

# ── Промпт-шаблоны ────────────────────────────────────────────────────────────
PROMPT_TEMPLATES = {
    "generic": """Ответь на вопрос на основе контекста.

КОНТЕКСТ:
{context}

ВОПРОС: {question}
ОТВЕТ:""",

    "expert_ved": """Ты — эксперт-таможенник с 10 годами практики в ВЭД России.
Отвечай чётко, структурированно, на основе контекста.
Используй термины: ТН ВЭД, ДТ, декларант, таможенный брокер — только если они уместны.
Если в контексте нет ответа — скажи об этом прямо.

КОНТЕКСТ:
{context}

ВОПРОС: {question}
ОТВЕТ ЭКСПЕРТА:""",

    "few_shot": """Ты помогаешь бизнесу с ВЭД-вопросами. Вот пример хорошего ответа:

Вопрос: Что такое таможенная декларация?
Ответ: Таможенная декларация (ДТ) — официальный документ, в котором декларант указывает сведения о товаре: код ТН ВЭД, стоимость, вес, страну происхождения. Подаётся при каждом пересечении таможенной границы.

Теперь ответь на новый вопрос в том же стиле. Используй только контекст ниже.

КОНТЕКСТ:
{context}

ВОПРОС: {question}
ОТВЕТ:""",
}

# ── Конфигурации параметров ────────────────────────────────────────────────────
CONFIGS = [
    # Базовая (как в task28)
    {"name": "baseline",       "temperature": 0.3, "num_predict": 600, "repeat_penalty": 1.0},
    # Холодная + короткая
    {"name": "cold_short",     "temperature": 0.1, "num_predict": 300, "repeat_penalty": 1.0},
    # Холодная + длинная
    {"name": "cold_long",      "temperature": 0.1, "num_predict": 1000, "repeat_penalty": 1.1},
    # Тёплая
    {"name": "warm",           "temperature": 0.5, "num_predict": 600, "repeat_penalty": 1.0},
    # Горячая (креативная)
    {"name": "hot",            "temperature": 0.9, "num_predict": 600, "repeat_penalty": 1.0},
    # Anti-repeat (борьба с повторами)
    {"name": "anti_repeat",    "temperature": 0.2, "num_predict": 600, "repeat_penalty": 1.3},
]


def generate(prompt: str, config: dict) -> tuple[str, float, int]:
    """Генерация с заданными параметрами. Возвращает (ответ, время, токенов)."""
    t0 = time.time()
    resp = _http.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature":    config["temperature"],
            "num_predict":    config["num_predict"],
            "repeat_penalty": config["repeat_penalty"],
        },
    }, timeout=300)
    resp.raise_for_status()
    elapsed = round(time.time() - t0, 1)
    data = resp.json()
    answer = data.get("response", "").strip()
    tokens = data.get("eval_count", 0)
    return answer, elapsed, tokens


def score(answer: str, question: str) -> int:
    """Оценка качества 1-5."""
    if not answer or len(answer) < 30:
        return 1
    if "❌" in answer or "ошибка" in answer.lower():
        return 1
    # Наличие ключевых слов из вопроса
    keywords = [w.lower() for w in question.split() if len(w) > 4]
    hits = sum(1 for k in keywords if k in answer.lower())
    # Штраф за повторы (простая эвристика)
    words = answer.split()
    unique_ratio = len(set(words)) / len(words) if words else 1
    if unique_ratio < 0.5:
        return 2  # много повторов
    if len(answer) > 400 and hits >= 2:
        return 5
    if len(answer) > 200 and hits >= 1:
        return 4
    if len(answer) > 100:
        return 3
    return 2


def mean(lst):
    return round(statistics.mean(lst), 2) if lst else 0


def main():
    print("=" * 70)
    print(f"  Task 29 — Оптимизация параметров: {MODEL}")
    print(f"  Конфигураций: {len(CONFIGS)} | Шаблонов: {len(PROMPT_TEMPLATES)} | Вопросов: {len(TEST_QUESTIONS)}")
    print("=" * 70)

    # Кешируем retrieval (одинаковый для всех)
    contexts = {}
    print("\n🔍 Retrieval (кешируем)...")
    for q in TEST_QUESTIONS:
        docs = retrieve(q, top_k=4)
        contexts[q] = "\n\n".join(f"[{d['title']}]\n{d['text'][:400]}" for d in docs)
        print(f"  ✓ {q[:40]}")

    # ── Фаза 1: перебор параметров (с лучшим шаблоном — expert_ved) ──────────
    print("\n\n📊 ФАЗА 1: Параметры (шаблон: expert_ved)\n")
    print(f"{'Конфиг':<16} {'temp':<6} {'tokens':<8} {'rep.pen':<8} {'avg_time':<10} {'avg_score':<10} {'tok/s'}")
    print("-" * 70)

    config_results = {}
    for cfg in CONFIGS:
        times, scores_list, tps_list = [], [], []
        for q in TEST_QUESTIONS:
            prompt = PROMPT_TEMPLATES["expert_ved"].format(
                context=contexts[q], question=q
            )
            try:
                ans, t, tok = generate(prompt, cfg)
                s = score(ans, q)
                times.append(t)
                scores_list.append(s)
                if t > 0 and tok > 0:
                    tps_list.append(round(tok / t, 1))
            except Exception as e:
                times.append(0); scores_list.append(1)

        avg_time  = mean(times)
        avg_score = mean(scores_list)
        avg_tps   = mean(tps_list)
        config_results[cfg["name"]] = {
            "config": cfg, "avg_time": avg_time,
            "avg_score": avg_score, "avg_tps": avg_tps,
        }
        print(f"{cfg['name']:<16} {cfg['temperature']:<6} {cfg['num_predict']:<8} "
              f"{cfg['repeat_penalty']:<8} {avg_time:<10} {avg_score:<10} {avg_tps}")

    # Лучшая конфигурация параметров
    best_cfg_name = max(config_results, key=lambda k: config_results[k]["avg_score"] * 2 - config_results[k]["avg_time"] / 30)
    best_cfg = config_results[best_cfg_name]["config"]
    print(f"\n🏆 Лучшая конфигурация: {best_cfg_name}")

    # ── Фаза 2: перебор промпт-шаблонов (с лучшими параметрами) ─────────────
    print("\n\n📊 ФАЗА 2: Промпт-шаблоны\n")
    print(f"{'Шаблон':<16} {'avg_time':<10} {'avg_score':<10} {'avg_len'}")
    print("-" * 50)

    template_results = {}
    for tname, template in PROMPT_TEMPLATES.items():
        times, scores_list, lens = [], [], []
        for q in TEST_QUESTIONS:
            prompt = template.format(context=contexts[q], question=q)
            try:
                ans, t, tok = generate(prompt, best_cfg)
                times.append(t)
                scores_list.append(score(ans, q))
                lens.append(len(ans))
            except Exception as e:
                times.append(0); scores_list.append(1); lens.append(0)

        avg_time  = mean(times)
        avg_score = mean(scores_list)
        avg_len   = mean(lens)
        template_results[tname] = {
            "avg_time": avg_time, "avg_score": avg_score, "avg_len": avg_len
        }
        print(f"{tname:<16} {avg_time:<10} {avg_score:<10} {avg_len}")

    best_template = max(template_results, key=lambda k: template_results[k]["avg_score"])
    print(f"\n🏆 Лучший шаблон: {best_template}")

    # ── Итог: до vs после ─────────────────────────────────────────────────────
    baseline = config_results.get("baseline", {})
    best     = config_results.get(best_cfg_name, {})

    print("\n\n" + "=" * 70)
    print("  ИТОГ: ДО vs ПОСЛЕ оптимизации")
    print("=" * 70)
    print(f"\n{'Метрика':<25} {'ДО (baseline)':<20} {'ПОСЛЕ (' + best_cfg_name + ')'}")
    print("-" * 65)
    print(f"{'Среднее время (с)':<25} {baseline.get('avg_time','?'):<20} {best.get('avg_time','?')}")
    print(f"{'Средняя оценка (1-5)':<25} {baseline.get('avg_score','?'):<20} {best.get('avg_score','?')}")
    print(f"{'Скорость (tok/s)':<25} {baseline.get('avg_tps','?'):<20} {best.get('avg_tps','?')}")
    print(f"{'Лучший шаблон':<25} {'generic':<20} {best_template}")

    # Сохраняем результаты
    results = {
        "best_config": best_cfg,
        "best_template": best_template,
        "config_results": config_results,
        "template_results": template_results,
    }
    import os
    out = os.path.join(os.path.dirname(__file__), "optimization_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 Сохранено: {out}")
    print(f"\n✅ Оптимальная конфигурация:")
    print(f"   temperature={best_cfg['temperature']}, max_tokens={best_cfg['num_predict']}, "
          f"repeat_penalty={best_cfg['repeat_penalty']}, template={best_template}")


if __name__ == "__main__":
    main()
