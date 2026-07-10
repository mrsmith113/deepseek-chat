#!/usr/bin/env python3
"""
Task 29 — Бенчмарк: ДО vs ПОСЛЕ оптимизации
Запускает 5 вопросов с базовыми и оптимальными параметрами.
Выводит детальное сравнение ответов и итоговую таблицу.
Также проверяет наличие квантованной модели.
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
OLLAMA_TAGS = "http://localhost:11434/api/tags"

_http = requests.Session()
_http.trust_env = False

# ── Конфигурация ДО (baseline из task28) ────────────────────────────────────
CONFIG_BEFORE = {
    "name": "baseline (task28)",
    "model": "qwen3:14b",
    "temperature": 0.3,
    "num_predict": 600,
    "repeat_penalty": 1.0,
    "prompt_template": "generic",
}

# ── Конфигурация ПОСЛЕ (оптимальная) ─────────────────────────────────────────
CONFIG_AFTER = {
    "name": "optimized",
    "model": "qwen3:14b",
    "temperature": 0.1,
    "num_predict": 800,
    "repeat_penalty": 1.1,
    "prompt_template": "expert_ved",
}

PROMPT_TEMPLATES = {
    "generic": "Ответь на вопрос на основе контекста.\n\nКОНТЕКСТ:\n{context}\n\nВОПРОС: {question}\nОТВЕТ:",
    "expert_ved": (
        "Ты — эксперт-таможенник с 10 годами практики в ВЭД России.\n"
        "Отвечай чётко, структурированно, на основе контекста.\n"
        "Если в контексте нет ответа — скажи об этом прямо.\n\n"
        "КОНТЕКСТ:\n{context}\n\nВОПРОС: {question}\nОТВЕТ ЭКСПЕРТА:"
    ),
}

QUESTIONS = [
    "Что такое нотификация ФСБ и кому она нужна?",
    "Как рассчитать таможенную пошлину на электронику?",
    "Какие документы нужны для параллельного импорта?",
    "Что такое ТН ВЭД и зачем нужен код товара?",
    "Как перевести деньги поставщику в Китай?",
]


def list_models() -> list[str]:
    try:
        r = _http.get(OLLAMA_TAGS, timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except:
        return []


def generate(question: str, context: str, cfg: dict) -> dict:
    template = PROMPT_TEMPLATES[cfg["prompt_template"]]
    prompt = template.format(context=context, question=question)

    t0 = time.time()
    resp = _http.post(OLLAMA_URL, json={
        "model": cfg["model"],
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature":    cfg["temperature"],
            "num_predict":    cfg["num_predict"],
            "repeat_penalty": cfg["repeat_penalty"],
        },
    }, timeout=300)
    resp.raise_for_status()
    elapsed = round(time.time() - t0, 1)
    data = resp.json()
    answer = data.get("response", "").strip()
    tokens = data.get("eval_count", 0)
    tps = round(tokens / elapsed, 1) if elapsed > 0 and tokens > 0 else 0
    return {"answer": answer, "time": elapsed, "tokens": tokens, "tps": tps}


def score(answer: str, question: str) -> int:
    if not answer or len(answer) < 30 or "❌" in answer:
        return 1
    keywords = [w.lower() for w in question.split() if len(w) > 4]
    hits = sum(1 for k in keywords if k in answer.lower())
    words = answer.split()
    unique_ratio = len(set(words)) / len(words) if words else 1
    if unique_ratio < 0.5:
        return 2
    if len(answer) > 500 and hits >= 2: return 5
    if len(answer) > 300 and hits >= 1: return 4
    if len(answer) > 150: return 3
    return 2


def mean(lst):
    return round(statistics.mean(lst), 2) if lst else 0


def main():
    # Информация о доступных моделях
    models = list_models()
    print("=" * 70)
    print("  Task 29 — Бенчмарк: ДО vs ПОСЛЕ оптимизации")
    print("=" * 70)
    print(f"\n📦 Доступные модели в Ollama: {', '.join(models)}")

    # Есть ли квантованная версия?
    has_quant = any("q4" in m or "q8" in m or "q5" in m for m in models)
    if has_quant:
        quant_models = [m for m in models if any(q in m for q in ["q4", "q8", "q5"])]
        print(f"✅ Квантованные модели: {', '.join(quant_models)}")
        CONFIG_AFTER["model"] = quant_models[0]
        print(f"   → Используем квантованную: {CONFIG_AFTER['model']}")
    else:
        print(f"ℹ️  Квантованных нет — сравниваем параметры/промпты на одной модели")
        print(f"   (чтобы добавить квантование: ollama pull qwen3:14b-q4_K_M)")

    print(f"\n⚙️  ДО:    {CONFIG_BEFORE['name']} | temp={CONFIG_BEFORE['temperature']} | "
          f"tokens={CONFIG_BEFORE['num_predict']} | prompt=generic")
    print(f"⚙️  ПОСЛЕ: {CONFIG_AFTER['name']}   | temp={CONFIG_AFTER['temperature']} | "
          f"tokens={CONFIG_AFTER['num_predict']} | prompt=expert_ved")

    # Кеш retrieval
    print("\n🔍 Retrieval...")
    contexts = {}
    for q in QUESTIONS:
        docs = retrieve(q, top_k=4)
        contexts[q] = "\n\n".join(f"[{d['title']}]\n{d['text'][:400]}" for d in docs)

    # Прогон
    before_times, before_scores, before_tps = [], [], []
    after_times, after_scores, after_tps = [], [], []
    all_pairs = []

    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n[{i}/{len(QUESTIONS)}] {q}")
        ctx = contexts[q]

        print(f"  ДО    ...", end=" ", flush=True)
        try:
            b = generate(q, ctx, CONFIG_BEFORE)
            bs = score(b["answer"], q)
            before_times.append(b["time"]); before_scores.append(bs); before_tps.append(b["tps"])
            print(f"{b['time']}с | score={bs} | {b['tps']} tok/s")
        except Exception as e:
            b = {"answer": f"❌ {e}", "time": 0, "tokens": 0, "tps": 0}; bs = 1
            print(f"ОШИБКА: {e}")

        print(f"  ПОСЛЕ ...", end=" ", flush=True)
        try:
            a = generate(q, ctx, CONFIG_AFTER)
            as_ = score(a["answer"], q)
            after_times.append(a["time"]); after_scores.append(as_); after_tps.append(a["tps"])
            print(f"{a['time']}с | score={as_} | {a['tps']} tok/s")
        except Exception as e:
            a = {"answer": f"❌ {e}", "time": 0, "tokens": 0, "tps": 0}; as_ = 1
            print(f"ОШИБКА: {e}")

        all_pairs.append({
            "question": q,
            "before": {**b, "score": bs},
            "after":  {**a, "score": as_},
        })

    # ── Итоговая таблица ──────────────────────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("  ИТОГ: ДО vs ПОСЛЕ")
    print("=" * 70)

    rows = [
        ("Среднее время (с)",     mean(before_times), mean(after_times)),
        ("Макс. время (с)",       max(before_times or [0]), max(after_times or [0])),
        ("Скорость (tok/s)",      mean(before_tps),  mean(after_tps)),
        ("Средняя оценка (1-5)",  mean(before_scores), mean(after_scores)),
        ("Мин. оценка",           min(before_scores or [0]), min(after_scores or [0])),
    ]
    print(f"\n{'Метрика':<28} {'ДО':<20} {'ПОСЛЕ':<20} {'Δ'}")
    print("-" * 75)
    for name, bv, av in rows:
        delta = round(av - bv, 2) if isinstance(av, float) else av - bv
        sign = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
        # Для времени — меньше лучше
        if "время" in name.lower() or "time" in name.lower():
            sign = "▼" if delta < 0 else ("▲" if delta > 0 else "=")
        print(f"{name:<28} {str(bv):<20} {str(av):<20} {sign}{abs(delta)}")

    # Детальные ответы
    print("\n\n📋 ДЕТАЛЬНЫЕ ОТВЕТЫ:\n")
    for pair in all_pairs:
        print(f"❓ {pair['question']}")
        print(f"  ДО    [{pair['before']['score']}/5, {pair['before']['time']}с]: "
              f"{pair['before']['answer'][:200].replace(chr(10), ' ')}...")
        print(f"  ПОСЛЕ [{pair['after']['score']}/5, {pair['after']['time']}с]: "
              f"{pair['after']['answer'][:200].replace(chr(10), ' ')}...")
        print()

    # Ресурсы
    print("💻 Потребление ресурсов:")
    try:
        import subprocess
        mem = subprocess.run(["free", "-h"], capture_output=True, text=True)
        lines = mem.stdout.strip().split("\n")
        for line in lines[:2]:
            print(f"   {line}")
    except:
        pass

    # Сохранение
    import os
    out = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "config_before": CONFIG_BEFORE,
            "config_after": CONFIG_AFTER,
            "summary": {r[0]: {"before": r[1], "after": r[2]} for r in rows},
            "pairs": [{
                "question": p["question"],
                "before_score": p["before"]["score"],
                "after_score": p["after"]["score"],
                "before_time": p["before"]["time"],
                "after_time": p["after"]["time"],
                "before_answer": p["before"]["answer"][:500],
                "after_answer": p["after"]["answer"][:500],
            } for p in all_pairs],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Сохранено: {out}")


if __name__ == "__main__":
    main()
