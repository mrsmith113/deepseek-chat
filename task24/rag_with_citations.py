"""
Task 24 — RAG с обязательными источниками, цитатами и режимом "не знаю".

Улучшения над task22:
  - Ответ ВСЕГДА содержит список источников (title + chunk_id + score)
  - Ответ ВСЕГДА содержит цитаты (прямые фрагменты из чанков)
  - Если max relevance score < порога — модель говорит "не знаю"

Запуск:
  python rag_with_citations.py "Как перевести деньги в Китай?"
  python rag_with_citations.py "Абракадабра бессмысленный запрос" --threshold 0.5
"""

import warnings
warnings.filterwarnings("ignore")

import argparse
import json
import re
import urllib.request

RAG_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:14b"
COLLECTION = "youtube_rag"

NOT_KNOW_THRESHOLD = 0.50


def http_post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def search_chunks(query: str, top_k: int = 5) -> list:
    result = http_post(f"{RAG_URL}/search", {"query": query, "top_k": top_k, "collection": COLLECTION})
    return result.get("results", [])


def ask_ollama_chat(messages: list) -> str:
    result = http_post(f"{OLLAMA_URL}/api/chat", {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    })
    return result.get("message", {}).get("content", "").strip()


SYSTEM_PROMPT = """Ты эксперт по ВЭД и таможне в России. Отвечаешь СТРОГО по предоставленным материалам.

Формат ответа — три секции, строго по шаблону:

ОТВЕТ:
<ответ на вопрос, 2-4 предложения, упоминай источники как [1], [2]>

ИСТОЧНИКИ:
<каждый источник на отдельной строке: [N] Название (chunk_id=X, score=Y)>

ЦИТАТЫ:
<2-3 прямые цитаты: [N] «цитата из материала»>

Если вопрос не покрыт материалами — напиши в секции ОТВЕТ: "Не знаю."
Никогда не придумывай информацию, которой нет в материалах."""


def build_context(chunks: list) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        title = c.get("title", "Неизвестно")
        chunk_id = c.get("chunk_id", i)
        score = c.get("score", 0)
        excerpt = c.get("excerpt", "")[:500]
        parts.append(f"[{i}] {title} (chunk_id={chunk_id}, score={score:.3f}):\n{excerpt}")
    return "\n\n".join(parts)


def _extract_section(text: str, header: str) -> str:
    pattern = rf"{header}:\s*\n(.*?)(?=\n(?:ОТВЕТ|ИСТОЧНИКИ|ЦИТАТЫ):|$)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def answer_with_citations(question: str, top_k: int = 5, threshold: float = NOT_KNOW_THRESHOLD) -> dict:
    chunks = search_chunks(question, top_k)

    if not chunks:
        return {
            "answer": "Не знаю. Материалы по данному вопросу не найдены в базе знаний.",
            "sources": [],
            "citations": [],
            "not_know": True,
            "chunks": [],
            "max_score": 0.0,
        }

    max_score = max(c.get("score", 0) for c in chunks)

    if max_score < threshold:
        return {
            "answer": (
                f"Не знаю. Найденные материалы недостаточно релевантны "
                f"(max score={max_score:.3f} < порога {threshold}). "
                f"Пожалуйста, уточните вопрос."
            ),
            "sources": [],
            "citations": [],
            "not_know": True,
            "chunks": chunks,
            "max_score": max_score,
        }

    context = build_context(chunks)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Материалы из базы знаний:\n\n{context}\n\nВопрос: {question}"},
    ]
    raw = ask_ollama_chat(messages)

    answer_text = _extract_section(raw, "ОТВЕТ")
    sources_raw = _extract_section(raw, "ИСТОЧНИКИ")
    citations_raw = _extract_section(raw, "ЦИТАТЫ")

    sources = [s.strip() for s in sources_raw.splitlines() if s.strip() and s.strip().startswith("[")]
    citations = [c.strip() for c in citations_raw.splitlines() if "«" in c and c.strip().startswith("[")]

    answer_final = answer_text or raw
    model_said_not_know = "не знаю" in answer_final.lower()

    return {
        "answer": answer_final,
        "sources": sources,
        "citations": citations,
        "not_know": model_said_not_know,
        "chunks": chunks,
        "max_score": max_score,
        "raw": raw,
    }


def print_result(result: dict, question: str = ""):
    print(f"\n{'═' * 70}")
    if question:
        print(f"  ❓ {question}")
        print(f"{'─' * 70}")
    if result["not_know"]:
        print(f"  ⚠️  НЕ ЗНАЮ  (max_score={result['max_score']:.3f})")
        print(f"  {result['answer']}")
    else:
        print(f"  💬 ОТВЕТ  (max_score={result['max_score']:.3f})")
        print(f"  {result['answer']}")
        print()
        print(f"  📚 ИСТОЧНИКИ ({len(result['sources'])} шт.):")
        for s in result["sources"]:
            print(f"    {s}")
        print()
        print(f"  📖 ЦИТАТЫ ({len(result['citations'])} шт.):")
        for c in result["citations"]:
            print(f"    {c}")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG с источниками, цитатами и режимом 'не знаю'")
    parser.add_argument("question", help="Вопрос")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=NOT_KNOW_THRESHOLD)
    args = parser.parse_args()

    result = answer_with_citations(args.question, args.top_k, args.threshold)
    print_result(result, args.question)
