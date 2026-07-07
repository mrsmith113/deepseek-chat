#!/usr/bin/env python3
"""
Task 26 — Локальная LLM через Ollama HTTP API
Модель: qwen3:14b (уже запущена на localhost:11434)
"""

import json
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:14b"


def ask(prompt: str, max_tokens: int = 300) -> dict:
    """Отправить запрос в Ollama и вернуть ответ + метрики."""
    t0 = time.time()
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,  # отключаем chain-of-thought для скорости
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    elapsed = time.time() - t0
    return {
        "answer": data.get("response", "").strip(),
        "elapsed": round(elapsed, 2),
        "tokens": data.get("eval_count", 0),
    }


QUERIES = [
    {
        "level": "Простой",
        "prompt": "Сколько будет 17 умножить на 6? Ответь только числом.",
    },
    {
        "level": "Средний",
        "prompt": (
            "Объясни простыми словами что такое RAG (Retrieval Augmented Generation) "
            "в 3-4 предложениях. Используй аналогию из жизни."
        ),
    },
    {
        "level": "Сложный",
        "prompt": (
            "Напиши Python-функцию chunk_text(text, chunk_size=500, overlap=50), "
            "которая делит текст на чанки с перекрытием. "
            "Добавь docstring и пример использования."
        ),
    },
]


def main():
    print(f"Модель: {MODEL}")
    print(f"URL:    {OLLAMA_URL}")
    print("=" * 60)

    for i, q in enumerate(QUERIES, 1):
        print(f"\n[Запрос {i} — {q['level']}]")
        print(f"Вопрос: {q['prompt'][:80]}...")
        result = ask(q["prompt"])
        print(f"Ответ ({result['elapsed']}с, {result['tokens']} токенов):")
        print(result["answer"])
        print("-" * 60)


if __name__ == "__main__":
    main()
