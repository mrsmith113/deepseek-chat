#!/usr/bin/env python3
"""
Task 27 — CLI-приложение с локальной LLM
Использует RAG-сервер (localhost:8000) → Qdrant → Qwen3 14B (Ollama)
Без облака, без API-ключей.
"""

import sys
import json
import time
import requests

RAG_URL   = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL     = "qwen3:14b"


def check_services():
    """Проверяет доступность RAG-сервера и Ollama."""
    ok = True
    try:
        r = requests.get(f"{RAG_URL}/health", timeout=3)
        print(f"✅ RAG-сервер: {r.json().get('status', 'ok')}")
    except Exception as e:
        print(f"⚠️  RAG-сервер недоступен ({e}) — работаем через Ollama напрямую")
        ok = False

    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"✅ Ollama: {', '.join(models)}")
    except Exception as e:
        print(f"❌ Ollama недоступна: {e}")
        sys.exit(1)

    return ok


def ask_with_rag(question: str) -> dict:
    """Задаёт вопрос через RAG-сервер (Qdrant + Qwen3 14B)."""
    t0 = time.time()
    resp = requests.post(f"{RAG_URL}/ask", json={
        "question": question,
        "top_k": 3,
        "collection": "youtube_rag",
    }, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return {
        "answer": data.get("answer", ""),
        "sources": data.get("sources", []),
        "elapsed": round(time.time() - t0, 1),
        "mode": "RAG + Qwen3 14B",
    }


def ask_direct(question: str) -> dict:
    """Задаёт вопрос напрямую в Ollama (без RAG)."""
    t0 = time.time()
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": question,
        "stream": False,
        "think": False,
        "options": {"num_predict": 500, "temperature": 0.7},
    }, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return {
        "answer": data.get("response", "").strip(),
        "sources": [],
        "elapsed": round(time.time() - t0, 1),
        "mode": f"Qwen3 14B (direct)",
    }


def print_result(result: dict):
    print(f"\n{'='*60}")
    print(f"[{result['mode']} | {result['elapsed']}с]")
    print(f"{'='*60}")
    print(result["answer"])
    if result["sources"]:
        print(f"\n📚 Источники:")
        for i, s in enumerate(result["sources"][:3], 1):
            title = s.get("title", "")
            score = s.get("score", "")
            print(f"  {i}. {title} (score: {score})")
    print()


def demo_mode(use_rag: bool):
    """Прогон 3 демо-запросов для видео."""
    queries = [
        "Что такое нотификация ФСБ?",
        "Как рассчитать таможенную пошлину на электронику?",
        "Какие документы нужны для параллельного импорта?",
    ]
    print("\n🎬 ДЕМО-РЕЖИМ: 3 запроса разной сложности\n")
    for i, q in enumerate(queries, 1):
        print(f"[Запрос {i}] {q}")
        try:
            result = ask_with_rag(q) if use_rag else ask_direct(q)
            print_result(result)
        except Exception as e:
            print(f"❌ Ошибка: {e}\n")


def interactive_mode(use_rag: bool):
    """Интерактивный режим — вводи вопросы вручную."""
    print("\n💬 Интерактивный режим (введи 'выход' для завершения)\n")
    while True:
        try:
            question = input("Вопрос: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nПока!")
            break
        if not question or question.lower() in ("выход", "exit", "quit", "q"):
            print("Пока!")
            break
        try:
            result = ask_with_rag(question) if use_rag else ask_direct(question)
            print_result(result)
        except Exception as e:
            print(f"❌ Ошибка: {e}\n")


def main():
    print("=" * 60)
    print("  Task 27 — CLI с локальной LLM (Qwen3 14B + RAG)")
    print("=" * 60)

    use_rag = check_services()

    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"

    if mode == "demo":
        demo_mode(use_rag)
    elif mode == "chat":
        interactive_mode(use_rag)
    else:
        # Одиночный вопрос из аргументов
        question = " ".join(sys.argv[1:])
        print(f"\nВопрос: {question}")
        result = ask_with_rag(question) if use_rag else ask_direct(question)
        print_result(result)


if __name__ == "__main__":
    main()
