"""
Task 22 — Сравнение качества ответов: с RAG vs без RAG.

Запускает 10 контрольных вопросов из questions.json,
показывает рядом ответы обоих режимов и считает метрики.

Запуск:
  python eval.py
  python eval.py --questions questions.json --top-k 5
"""

import warnings
warnings.filterwarnings("ignore")

import json
import argparse
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
    result = http_post(f"{RAG_URL}/search", {"query": query, "top_k": top_k, "collection": COLLECTION})
    return result.get("results", [])


def ask_ollama(prompt: str, num_predict: int = 2048) -> str:
    result = http_post(f"{OLLAMA_URL}/api/generate", {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": num_predict},
    })
    return result.get("response", "").strip()


def answer_direct(question: str) -> str:
    prompt = f"Ты эксперт по ВЭД и таможне в России.\n\nВопрос: {question}\n\nОтветь кратко."
    return ask_ollama(prompt)


def answer_with_rag(question: str, top_k: int = 5) -> tuple:
    chunks = search_chunks(question, top_k)
    if not chunks:
        return "Релевантные материалы не найдены.", [], 0.0

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        excerpt = chunk.get("excerpt", "")[:400]
        context_parts.append(f"[{i}] {chunk.get('title', '?')}:\n{excerpt}")

    context = "\n\n".join(context_parts)
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)

    # /no_think отключает режим мышления Qwen3 — без него thinking-блок
    # съедает все токены до num_predict и ответ получается пустым
    prompt = f"""Ты эксперт по ВЭД и таможне в России. /no_think

Материалы из базы знаний:
{context}

Вопрос: {question}

Ответь на основе материалов. Укажи источники [1], [2]."""

    answer = ask_ollama(prompt)
    return answer, chunks, avg_score


def keyword_hit_rate(answer: str, keywords: list) -> float:
    """Доля ключевых слов найденных в ответе."""
    if not keywords:
        return 0.0
    found = sum(1 for kw in keywords if kw.lower() in answer.lower())
    return found / len(keywords)


def source_hit_rate(chunks: list, expected_sources: list) -> float:
    """Доля ожидаемых источников которые попали в топ чанков."""
    if not expected_sources or not chunks:
        return 0.0
    titles = " ".join(c.get("title", "") for c in chunks).lower()
    found = sum(1 for src in expected_sources if src.lower() in titles)
    return found / len(expected_sources)


def run_eval(questions_file: str, top_k: int):
    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    results = []
    total_kw_direct = 0
    total_kw_rag = 0
    total_src_rag = 0

    print(f"\n{'═' * 70}")
    print("  TASK 22: ОЦЕНКА КАЧЕСТВА RAG vs DIRECT")
    print(f"  {len(questions)} контрольных вопросов | collection={COLLECTION}")
    print(f"{'═' * 70}\n")

    for q in questions:
        qid = q["id"]
        question = q["question"]
        keywords = q.get("expected_keywords", [])
        exp_sources = q.get("expected_sources", [])

        print(f"[{qid}/10] {question}")
        print("  Генерирую ответы...", end=" ", flush=True)

        direct_ans = answer_direct(question)
        rag_ans, chunks, avg_score = answer_with_rag(question, top_k)

        kw_direct = keyword_hit_rate(direct_ans, keywords)
        kw_rag = keyword_hit_rate(rag_ans, keywords)
        src_rag = source_hit_rate(chunks, exp_sources)

        total_kw_direct += kw_direct
        total_kw_rag += kw_rag
        total_src_rag += src_rag

        print(f"done")
        print(f"  Direct  keywords: {kw_direct:.0%} | RAG keywords: {kw_rag:.0%} | Sources: {src_rag:.0%} | Avg score: {avg_score:.3f}")

        results.append({
            "id": qid,
            "question": question,
            "direct_answer": direct_ans,
            "rag_answer": rag_ans,
            "rag_sources": [{"title": c.get("title"), "score": c.get("score")} for c in chunks],
            "metrics": {
                "kw_hit_direct": round(kw_direct, 2),
                "kw_hit_rag": round(kw_rag, 2),
                "source_hit_rag": round(src_rag, 2),
                "avg_chunk_score": round(avg_score, 3),
            }
        })

    n = len(questions)
    avg_kw_direct = total_kw_direct / n
    avg_kw_rag = total_kw_rag / n
    avg_src = total_src_rag / n

    print(f"\n{'═' * 70}")
    print("  ИТОГОВЫЕ МЕТРИКИ")
    print(f"{'═' * 70}")
    print(f"  Keyword hit rate (Direct): {avg_kw_direct:.1%}")
    print(f"  Keyword hit rate (RAG):    {avg_kw_rag:.1%}  {'✅ лучше' if avg_kw_rag > avg_kw_direct else '⚠️ хуже'}")
    print(f"  Source hit rate  (RAG):    {avg_src:.1%}")
    winner = "RAG" if avg_kw_rag > avg_kw_direct else "DIRECT"
    print(f"\n  🏆 Победитель по ключевым словам: {winner}")
    print(f"{'═' * 70}\n")

    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "kw_hit_direct_avg": round(avg_kw_direct, 3),
                "kw_hit_rag_avg": round(avg_kw_rag, 3),
                "source_hit_rag_avg": round(avg_src, 3),
                "winner": winner,
            },
            "questions": results,
        }, f, ensure_ascii=False, indent=2)

    print("  Детальные результаты → eval_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="questions.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    run_eval(args.questions, args.top_k)
