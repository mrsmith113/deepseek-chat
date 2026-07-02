"""
Task 24 — Оценка: источники, цитаты, семантическое совпадение.

Проверяет 10 вопросов из task22/questions.json:
  has_sources     — есть ли источники в ответе
  has_citations   — есть ли прямые цитаты
  semantic_match  — совпадают ли ключевые слова ответа с цитатами
  not_know        — сработал ли режим "не знаю"

Запуск:
  python eval_citations.py
  python eval_citations.py --threshold 0.45
"""

import warnings
warnings.filterwarnings("ignore")

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rag_with_citations import answer_with_citations

QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "task22", "questions.json")


def semantic_match_score(answer: str, citations: list) -> float:
    """Доля значимых слов ответа, встречающихся в цитатах."""
    if not citations:
        return 0.0
    citation_text = " ".join(citations).lower()
    words = [w for w in answer.lower().split() if len(w) > 4]
    if not words:
        return 0.0
    return sum(1 for w in words if w in citation_text) / len(words)


def run_eval(threshold: float):
    with open(QUESTIONS_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    results = []
    n_sources = n_citations = n_not_know = 0
    sem_total = 0.0

    print(f"\n{'═' * 70}")
    print("  TASK 24 — ИСТОЧНИКИ, ЦИТАТЫ И «НЕ ЗНАЮ»")
    print(f"  threshold={threshold} | collection=youtube_rag")
    print(f"{'═' * 70}\n")

    for q in questions:
        qid = q["id"]
        question = q["question"]
        print(f"[{qid:02d}/10] {question[:55]}...", end=" ", flush=True)

        r = answer_with_citations(question, threshold=threshold)

        has_src = len(r["sources"]) > 0
        has_cit = len(r["citations"]) > 0
        sem = semantic_match_score(r["answer"], r["citations"])
        nk = r["not_know"]

        n_sources += int(has_src)
        n_citations += int(has_cit)
        n_not_know += int(nk)
        sem_total += sem

        icon = "⚠️ " if nk else "✅"
        print(
            f"{icon} src={'✓' if has_src else '✗'} "
            f"cit={'✓' if has_cit else '✗'} "
            f"sem={sem:.0%} "
            f"score={r['max_score']:.3f}"
        )

        results.append({
            "id": qid,
            "question": question,
            "answer": r["answer"][:300],
            "sources": r["sources"],
            "citations": r["citations"],
            "has_sources": has_src,
            "has_citations": has_cit,
            "semantic_match": round(sem, 3),
            "not_know": nk,
            "max_score": round(r["max_score"], 3),
        })

    n = len(questions)
    src_rate = n_sources / n
    cit_rate = n_citations / n
    sem_avg = sem_total / n

    print(f"\n{'═' * 70}")
    print("  ИТОГ")
    print(f"{'═' * 70}")
    print(f"  Источники в ответе:      {src_rate:.0%}  ({n_sources}/{n})")
    print(f"  Цитаты в ответе:         {cit_rate:.0%}  ({n_citations}/{n})")
    print(f"  Семантическое совпад.:   {sem_avg:.0%}")
    print(f"  Режим «не знаю»:         {n_not_know}/{n}")
    print(f"{'═' * 70}\n")

    out = {
        "config": {"threshold": threshold},
        "summary": {
            "sources_rate": round(src_rate, 3),
            "citations_rate": round(cit_rate, 3),
            "semantic_match_avg": round(sem_avg, 3),
            "not_know_count": n_not_know,
        },
        "questions": results,
    }
    with open("eval_citations_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("  Детали → eval_citations_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.50)
    args = parser.parse_args()
    run_eval(args.threshold)
