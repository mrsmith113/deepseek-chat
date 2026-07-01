"""
Task 22 — RAG-агент с двумя режимами: с RAG и без RAG.

Использует:
  - GigaEmbeddings + Qdrant :6333 для поиска чанков (RAG-режим)
  - Qwen3 14B через Ollama для генерации ответа

Запуск:
  python rag_agent.py --mode rag "Как перевести деньги в Китай?"
  python rag_agent.py --mode direct "Как перевести деньги в Китай?"
  python rag_agent.py --mode both "Как перевести деньги в Китай?"
"""

import warnings
warnings.filterwarnings("ignore")

import argparse
import json
import urllib.request

RAG_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:14b"
COLLECTION = "youtube_rag"


def http_post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def search_chunks(query: str, top_k: int = 5) -> list:
    """Ищет релевантные чанки в Qdrant через RAG-сервер."""
    result = http_post(f"{RAG_URL}/search", {"query": query, "top_k": top_k, "collection": COLLECTION})
    return result.get("results", [])


def ask_ollama(prompt: str) -> str:
    """Отправляет промпт в Qwen3 14B через Ollama."""
    result = http_post(f"{OLLAMA_URL}/api/generate", {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    })
    return result.get("response", "").strip()


def answer_direct(question: str) -> str:
    """Режим без RAG: вопрос прямо в LLM."""
    prompt = f"""Ты эксперт по внешнеэкономической деятельности (ВЭД), таможне и сертификации в России.

Вопрос: {question}

Ответь кратко и по делу."""
    return ask_ollama(prompt)


def answer_with_rag(question: str, top_k: int = 5) -> tuple:
    """Режим с RAG: поиск чанков → контекст → LLM."""
    chunks = search_chunks(question, top_k)

    if not chunks:
        return "Релевантные материалы не найдены.", []

    # Формируем контекст из найденных чанков
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("title", "Неизвестный источник")
        date = chunk.get("date", "")
        excerpt = chunk.get("excerpt", "")[:500]
        context_parts.append(f"[{i}] {source} ({date}):\n{excerpt}")

    context = "\n\n".join(context_parts)

    prompt = f"""Ты эксперт по внешнеэкономической деятельности (ВЭД), таможне и сертификации в России.

Используй следующие материалы из базы знаний для ответа:

{context}

Вопрос: {question}

Ответь на основе предоставленных материалов. Укажи номера источников [1], [2] и т.д. при ссылке на них."""

    answer = ask_ollama(prompt)
    return answer, chunks


def print_separator(char="─", width=70):
    print(char * width)


def run(question: str, mode: str):
    print(f"\n{'═' * 70}")
    print(f"  ВОПРОС: {question}")
    print(f"{'═' * 70}\n")

    if mode in ("direct", "both"):
        print("▶ РЕЖИМ БЕЗ RAG (чистый LLM)")
        print_separator()
        answer = answer_direct(question)
        print(answer)
        print()

    if mode in ("rag", "both"):
        print("▶ РЕЖИМ С RAG (поиск + LLM)")
        print_separator()
        answer, chunks = answer_with_rag(question)

        print("📚 Источники:")
        for i, chunk in enumerate(chunks, 1):
            print(f"  [{i}] {chunk.get('title', '?')} (score={chunk.get('score', 0):.3f})")
        print()
        print("💬 Ответ:")
        print(answer)
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG-агент: с RAG и без RAG")
    parser.add_argument("question", help="Вопрос для агента")
    parser.add_argument("--mode", choices=["rag", "direct", "both"], default="both",
                        help="Режим: rag | direct | both (по умолчанию: both)")
    parser.add_argument("--top-k", type=int, default=5, help="Количество чанков для RAG")
    args = parser.parse_args()

    run(args.question, args.mode)
