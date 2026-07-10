#!/usr/bin/env python3
"""
Task 28 — Сравнение: локальная LLM vs облачная LLM
Одинаковый retrieval (Qdrant youtube_rag), разная генерация:
  - LOCAL:  Qwen3 14B через Ollama
  - CLOUD:  DeepSeek через API
Метрики: время ответа, длина, субъективная оценка (1-5).
"""

import os
import time
import json
import requests
import statistics
import warnings
warnings.filterwarnings("ignore")

from rag_local import retrieve, generate_local

DEEPSEEK_URL   = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_KEY   = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"

TEST_QUESTIONS = [
    "Что такое нотификация ФСБ и кому она нужна?",
    "Как рассчитать таможенную пошлину на электронику?",
    "Какие документы нужны для параллельного импорта?",
    "Что такое ТН ВЭД и зачем нужен код товара?",
    "Как перевести деньги поставщику в Китай в 2024 году?",
]

REPEAT = 2  # сколько раз повторять каждый вопрос для оценки стабильности


def generate_cloud(question: str, context: str) -> tuple[str, float]:
    """Генерация через DeepSeek API."""
    prompt = f"""Ты эксперт по ВЭД и таможенному оформлению. Отвечай только на основе предоставленного контекста.
Если ответа в контексте нет — так и скажи.

КОНТЕКСТ:
{context}

ВОПРОС: {question}"""

    t0 = time.time()
    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 600,
            "temperature": 0.3,
        },
        timeout=60,
    )
    resp.raise_for_status()
    elapsed = round(time.time() - t0, 1)
    answer = resp.json()["choices"][0]["message"]["content"].strip()
    return answer, elapsed


def run_one(question: str, context: str) -> dict:
    """Прогоняет вопрос через оба режима, возвращает результаты."""
    print(f"  → LOCAL (Qwen3 14B)...", end=" ", flush=True)
    try:
        local_ans, local_time = generate_local(question, context)
        print(f"{local_time}с")
    except Exception as e:
        local_ans, local_time = f"❌ Ошибка: {e}", 0.0
        print(f"ОШИБКА")

    print(f"  → CLOUD (DeepSeek)...", end=" ", flush=True)
    try:
        cloud_ans, cloud_time = generate_cloud(question, context)
        print(f"{cloud_time}с")
    except Exception as e:
        cloud_ans, cloud_time = f"❌ Ошибка: {e}", 0.0
        print(f"ОШИБКА")

    return {
        "local":  {"answer": local_ans,  "time": local_time,  "len": len(local_ans)},
        "cloud":  {"answer": cloud_ans,  "time": cloud_time,  "len": len(cloud_ans)},
    }


def score_answer(answer: str, question: str) -> int:
    """
    Автоматическая оценка качества 1-5:
    - 5: развёрнутый ответ, содержит ключевые слова из вопроса
    - 4: хороший ответ
    - 3: частичный ответ
    - 2: короткий / нет контекста
    - 1: ошибка / отказ ответить
    """
    if "❌" in answer or len(answer) < 30:
        return 1
    keywords = [w.lower() for w in question.split() if len(w) > 4]
    hits = sum(1 for k in keywords if k in answer.lower())
    if len(answer) > 400 and hits >= 2:
        return 5
    if len(answer) > 200 and hits >= 1:
        return 4
    if len(answer) > 100:
        return 3
    return 2


def main():
    print("=" * 65)
    print("  Task 28 — Local LLM vs Cloud LLM: сравнение")
    print(f"  LOCAL:  Qwen3 14B (Ollama)")
    print(f"  CLOUD:  DeepSeek ({DEEPSEEK_MODEL})")
    print(f"  INDEX:  youtube_rag (Qdrant, неделя 6)")
    print(f"  Вопросов: {len(TEST_QUESTIONS)} × {REPEAT} повторов")
    print("=" * 65)

    all_results = []
    local_times, cloud_times = [], []
    local_scores, cloud_scores = [], []
    local_lens, cloud_lens = [], []

    for qi, question in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{qi}/{len(TEST_QUESTIONS)}] {question}")

        # Retrieval одинаковый для обоих
        docs = retrieve(question, top_k=5)
        context = "\n\n".join(f"[{d['title']}]\n{d['text'][:500]}" for d in docs)

        run_data = {"question": question, "sources": [d['title'] for d in docs[:3]], "runs": []}

        for r in range(REPEAT):
            if REPEAT > 1:
                print(f"  Повтор {r+1}/{REPEAT}")
            res = run_one(question, context)

            # Оценка качества
            res["local"]["score"] = score_answer(res["local"]["answer"], question)
            res["cloud"]["score"] = score_answer(res["cloud"]["answer"], question)

            local_times.append(res["local"]["time"])
            cloud_times.append(res["cloud"]["time"])
            local_scores.append(res["local"]["score"])
            cloud_scores.append(res["cloud"]["score"])
            local_lens.append(res["local"]["len"])
            cloud_lens.append(res["cloud"]["len"])

            run_data["runs"].append(res)

        all_results.append(run_data)

    # ── Сводная таблица метрик ────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  ИТОГОВЫЕ МЕТРИКИ")
    print("=" * 65)

    def safe_mean(lst):
        return round(statistics.mean(lst), 2) if lst else 0

    def safe_stdev(lst):
        return round(statistics.stdev(lst), 2) if len(lst) > 1 else 0

    rows = [
        ("Среднее время (с)",      safe_mean(local_times),   safe_mean(cloud_times)),
        ("Макс. время (с)",        max(local_times or [0]),  max(cloud_times or [0])),
        ("Мин. время (с)",         min(local_times or [0]),  min(cloud_times or [0])),
        ("Разброс (σ, с)",         safe_stdev(local_times),  safe_stdev(cloud_times)),
        ("Средняя длина (симв.)",  safe_mean(local_lens),    safe_mean(cloud_lens)),
        ("Средняя оценка (1-5)",   safe_mean(local_scores),  safe_mean(cloud_scores)),
        ("Мин. оценка",            min(local_scores or [0]), min(cloud_scores or [0])),
    ]

    print(f"\n{'Метрика':<30} {'LOCAL (Qwen3)':<20} {'CLOUD (DeepSeek)':<20}")
    print("-" * 70)
    for name, lv, cv in rows:
        print(f"{name:<30} {str(lv):<20} {str(cv):<20}")

    # Вывод
    print("\n📊 Выводы:")
    if safe_mean(local_times) < safe_mean(cloud_times):
        print(f"  ⚡ Скорость: LOCAL быстрее на {round(safe_mean(cloud_times)-safe_mean(local_times),1)}с")
    else:
        print(f"  ⚡ Скорость: CLOUD быстрее на {round(safe_mean(local_times)-safe_mean(cloud_times),1)}с")

    if safe_mean(local_scores) >= safe_mean(cloud_scores):
        print(f"  🎯 Качество: LOCAL ≥ CLOUD ({safe_mean(local_scores)} vs {safe_mean(cloud_scores)})")
    else:
        print(f"  🎯 Качество: CLOUD лучше ({safe_mean(cloud_scores)} vs {safe_mean(local_scores)})")

    stdev_l = safe_stdev(local_times)
    stdev_c = safe_stdev(cloud_times)
    if stdev_l <= stdev_c:
        print(f"  🔒 Стабильность: LOCAL стабильнее (σ={stdev_l}с vs {stdev_c}с)")
    else:
        print(f"  🔒 Стабильность: CLOUD стабильнее (σ={stdev_c}с vs {stdev_l}с)")

    # Сохраняем JSON для видео
    output = {
        "summary": {r[0]: {"local": r[1], "cloud": r[2]} for r in rows},
        "results": [
            {
                "question": rd["question"],
                "sources": rd["sources"],
                "local_answer": rd["runs"][0]["local"]["answer"][:300],
                "cloud_answer": rd["runs"][0]["cloud"]["answer"][:300],
                "local_time": rd["runs"][0]["local"]["time"],
                "cloud_time": rd["runs"][0]["cloud"]["time"],
            }
            for rd in all_results
        ]
    }
    import os
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Результаты сохранены: {out_path}")


if __name__ == "__main__":
    main()
