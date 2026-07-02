"""
Task 23 — Реранкинг и фильтрация.

Сравнивает три режима RAG:
  mode1 — baseline (top-5, без фильтра, оригинальный запрос)
  mode2 — threshold filter (top-10 → score >= 0.65 → MMR top-5)
  mode3 — query rewrite + threshold filter + MMR

Запуск:
  python eval.py
  python eval.py --top-k 10 --threshold 0.65
"""

import warnings
warnings.filterwarnings("ignore")

import json
import argparse
import urllib.request
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from reranker import rerank, threshold_filter
from query_rewriter import rewrite_query

RAG_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:14b"
COLLECTION = "youtube_rag"
QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "task22", "questions.json")


def http_post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def search_chunks(query: str, top_k: int = 10) -> list:
    result = http_post(f"{RAG_URL}/search", {"query": query, "top_k": top_k, "collection": COLLECTION})
    return result.get("results", [])


def ask_ollama(prompt: str) -> str:
    result = http_post(f"{OLLAMA_URL}/api/generate", {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 2048},
    })
    return result.get("response", "").strip()


def build_rag_answer(question: str, chunks: list) -> tuple[str, float]:
    if not chunks:
        return "Релевантные материалы не найдены.", 0.0
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)
    context = "\n\n".join(
        f"[{i}] {c.get('title', '?')}:\n{c.get('excerpt', '')[:400]}"
        for i, c in enumerate(chunks, 1)
    )
    prompt = f"""Ты эксперт по ВЭД и таможне в России. /no_think

Материалы из базы знаний:
{context}

Вопрос: {question}

Ответь на основе материалов. Укажи источники [1], [2]."""
    return ask_ollama(prompt), avg_score


def keyword_hit_rate(answer: str, keywords: list) -> float:
    if not keywords:
        return 0.0
    return sum(1 for kw in keywords if kw.lower() in answer.lower()) / len(keywords)


def source_hit_rate(chunks: list, expected: list) -> float:
    if not expected or not chunks:
        return 0.0
    titles = " ".join(c.get("title", "") for c in chunks).lower()
    return sum(1 for s in expected if s.lower() in titles) / len(expected)


def run_eval(top_k: int, threshold: float):
    with open(QUESTIONS_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    totals = {m: {"kw": 0.0, "src": 0.0} for m in ("mode1", "mode2", "mode3")}
    results = []

    print(f"\n{'═' * 70}")
    print("  TASK 23: РЕРАНКИНГ И ФИЛЬТРАЦИЯ")
    print(f"  top_k={top_k} | threshold={threshold} | collection={COLLECTION}")
    print(f"{'═' * 70}\n")

    for q in questions:
        qid = q["id"]
        question = q["question"]
        keywords = q.get("expected_keywords", [])
        exp_sources = q.get("expected_sources", [])

        print(f"[{qid}/10] {question}")
        print("  Генерирую...", end=" ", flush=True)

        # Mode 1: baseline — top-5, без фильтра
        chunks1 = search_chunks(question, top_k=5)
        ans1, score1 = build_rag_answer(question, chunks1)

        # Mode 2: threshold + MMR
        chunks2_raw = search_chunks(question, top_k=top_k)
        chunks2 = rerank(chunks2_raw, top_k=5, min_score=threshold)
        ans2, score2 = build_rag_answer(question, chunks2)

        # Mode 3: query rewrite + threshold + MMR
        rewritten = rewrite_query(question)
        chunks3_raw = search_chunks(rewritten, top_k=top_k)
        chunks3 = rerank(chunks3_raw, top_k=5, min_score=threshold)
        ans3, score3 = build_rag_answer(question, chunks3)

        kw1 = keyword_hit_rate(ans1, keywords)
        kw2 = keyword_hit_rate(ans2, keywords)
        kw3 = keyword_hit_rate(ans3, keywords)
        src1 = source_hit_rate(chunks1, exp_sources)
        src2 = source_hit_rate(chunks2, exp_sources)
        src3 = source_hit_rate(chunks3, exp_sources)

        for m, kw, src in [("mode1", kw1, src1), ("mode2", kw2, src2), ("mode3", kw3, src3)]:
            totals[m]["kw"] += kw
            totals[m]["src"] += src

        print("done")
        print(f"  Baseline  kw={kw1:.0%} src={src1:.0%} score={score1:.3f}")
        print(f"  +filter   kw={kw2:.0%} src={src2:.0%} score={score2:.3f} chunks_after={len(chunks2)}/{top_k}")
        print(f"  +rewrite  kw={kw3:.0%} src={src3:.0%} score={score3:.3f} | q: {rewritten[:60]}")

        results.append({
            "id": qid, "question": question, "rewritten": rewritten,
            "mode1": {"answer": ans1, "kw": round(kw1, 2), "src": round(src1, 2), "score": round(score1, 3)},
            "mode2": {"answer": ans2, "kw": round(kw2, 2), "src": round(src2, 2), "score": round(score2, 3), "chunks_kept": len(chunks2)},
            "mode3": {"answer": ans3, "kw": round(kw3, 2), "src": round(src3, 2), "score": round(score3, 3), "chunks_kept": len(chunks3)},
        })

    n = len(questions)
    kw1_avg = totals["mode1"]["kw"] / n
    kw2_avg = totals["mode2"]["kw"] / n
    kw3_avg = totals["mode3"]["kw"] / n
    src1_avg = totals["mode1"]["src"] / n
    src2_avg = totals["mode2"]["src"] / n
    src3_avg = totals["mode3"]["src"] / n

    best_kw = max(kw1_avg, kw2_avg, kw3_avg)

    print(f"\n{'═' * 70}")
    print("  ИТОГОВЫЕ МЕТРИКИ")
    print(f"{'═' * 70}")
    print(f"  {'Режим':<30} {'Keywords':>10} {'Sources':>10}")
    print(f"  {'─'*50}")
    print(f"  {'Baseline (top-5, no filter)':<30} {kw1_avg:>9.1%} {src1_avg:>9.1%}  {'🏆' if kw1_avg == best_kw else ''}")
    print(f"  {f'+filter (score>={threshold}, MMR)':<30} {kw2_avg:>9.1%} {src2_avg:>9.1%}  {'🏆' if kw2_avg == best_kw else ''}")
    print(f"  {'+rewrite +filter +MMR':<30} {kw3_avg:>9.1%} {src3_avg:>9.1%}  {'🏆' if kw3_avg == best_kw else ''}")
    print(f"{'═' * 70}\n")

    summary = {
        "config": {"top_k": top_k, "threshold": threshold},
        "baseline": {"kw_avg": round(kw1_avg, 3), "src_avg": round(src1_avg, 3)},
        "filter": {"kw_avg": round(kw2_avg, 3), "src_avg": round(src2_avg, 3)},
        "rewrite_filter": {"kw_avg": round(kw3_avg, 3), "src_avg": round(src3_avg, 3)},
    }

    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "questions": results}, f, ensure_ascii=False, indent=2)

    print("  Детальные результаты → eval_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.65)
    args = parser.parse_args()
    run_eval(args.top_k, args.threshold)
