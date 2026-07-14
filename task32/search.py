"""Векторный поиск по чанкам (документация + код).

Бэкенд эмбеддингов — TF-IDF на чистом stdlib (math/collections): работает
офлайн, без внешних зависимостей и без поднятого Qdrant/Ollama. Метрика —
косинусная близость. Возвращает топ-K чанков со score.

Переиспользован из task31.1 (ассистент разработчика) без изменений логики —
одна ответственность: retrieval.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[а-яёa-z0-9_]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


class TfidfBackend:
    """TF-IDF векторизация + косинус. Без внешних зависимостей."""

    name = "tfidf"

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        docs = [tokenize(c["text"]) for c in chunks]
        n = len(docs)
        df: Counter = Counter()
        for toks in docs:
            for t in set(toks):
                df[t] += 1
        self.idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}
        self.vectors = [self._vec(toks) for toks in docs]

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        total = len(toks) or 1
        v = {t: (c / total) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def _cos(a: dict, b: dict) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())

    def search(self, query: str, k: int = 4) -> list[tuple[float, dict]]:
        qv = self._vec(tokenize(query))
        scored = [(self._cos(qv, dv), self.chunks[i])
                  for i, dv in enumerate(self.vectors)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


def build_backend(chunks: list[dict]) -> TfidfBackend:
    return TfidfBackend(chunks)


if __name__ == "__main__":
    import json
    from pathlib import Path
    idx = json.loads((Path(__file__).parent / "index.json").read_text("utf-8"))
    be = build_backend(idx)
    print(f"backend={be.name}, чанков={len(idx)}")
    for score, ch in be.search("как устроен пайплайн ревью", k=3):
        print(f"  {score:.3f}  {ch['source']}::{ch['section']}")
