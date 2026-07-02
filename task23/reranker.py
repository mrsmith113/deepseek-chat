"""
Reranker и фильтр релевантности для RAG-пайплайна.

Два метода:
  1. threshold_filter — отсекает чанки ниже порога cosine similarity
  2. mmr_rerank — Maximum Marginal Relevance: максимум релевантности,
     минимум повторения (диверсификация результатов)
"""

import math


def threshold_filter(chunks: list, min_score: float = 0.65) -> list:
    """Оставить только чанки с similarity >= min_score."""
    return [c for c in chunks if c.get("score", 0.0) >= min_score]


def _title_overlap(a: str, b: str) -> float:
    """Простое пересечение слов заголовков (Jaccard)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def mmr_rerank(chunks: list, top_k: int = 5, lambda_param: float = 0.7) -> list:
    """
    Maximum Marginal Relevance.

    Выбираем top_k чанков, балансируя между:
      - релевантностью (similarity score из Qdrant)
      - разнообразием (избегаем дублирующих источников)

    lambda_param: 1.0 = чистая релевантность, 0.0 = чистое разнообразие
    """
    if not chunks:
        return []

    selected = []
    remaining = list(chunks)

    while remaining and len(selected) < top_k:
        best = None
        best_score = -math.inf

        for candidate in remaining:
            relevance = candidate.get("score", 0.0)

            if not selected:
                redundancy = 0.0
            else:
                redundancy = max(
                    _title_overlap(
                        candidate.get("title", ""),
                        s.get("title", "")
                    )
                    for s in selected
                )

            mmr_score = lambda_param * relevance - (1 - lambda_param) * redundancy

            if mmr_score > best_score:
                best_score = mmr_score
                best = candidate

        if best is not None:
            selected.append(best)
            remaining.remove(best)

    return selected


def rerank(chunks: list, top_k: int = 5, min_score: float = 0.65) -> list:
    """Полный пайплайн: threshold → MMR."""
    filtered = threshold_filter(chunks, min_score)
    if not filtered:
        # fallback: если всё отсеялось — берём лучший чанк без фильтра
        filtered = sorted(chunks, key=lambda c: c.get("score", 0), reverse=True)[:1]
    return mmr_rerank(filtered, top_k)
