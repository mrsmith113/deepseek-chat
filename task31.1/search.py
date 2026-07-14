"""Векторный поиск по чанкам документации.

Два бэкенда эмбеддингов:
  * tfidf  — чистый stdlib (math/collections), работает офлайн без зависимостей.
  * dense  — sentence-transformers, если установлен (env EMB_BACKEND=dense).

Метрика — косинусная близость. Возвращает топ-K чанков с score.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

_WORD = re.compile(r"[а-яёa-z0-9_]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


# ---------------------------------------------------------------- TF-IDF -----
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
        # idf со сглаживанием
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


# ------------------------------------------------------------ dense (opt) ----
class DenseBackend:
    """sentence-transformers, если доступен."""

    name = "dense"

    def __init__(self, chunks: list[dict]):
        from sentence_transformers import SentenceTransformer  # lazy
        import numpy as np
        self._np = np
        self.chunks = chunks
        model_name = os.getenv("EMB_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.model = SentenceTransformer(model_name)
        emb = self.model.encode([c["text"] for c in chunks],
                                normalize_embeddings=True)
        self.emb = np.asarray(emb, dtype="float32")

    def search(self, query: str, k: int = 4) -> list[tuple[float, dict]]:
        np = self._np
        q = self.model.encode([query], normalize_embeddings=True)[0]
        sims = self.emb @ np.asarray(q, dtype="float32")
        idx = sims.argsort()[::-1][:k]
        return [(float(sims[i]), self.chunks[i]) for i in idx]


def build_backend(chunks: list[dict]):
    """Выбирает бэкенд: EMB_BACKEND=dense → sentence-transformers, иначе tfidf."""
    want = os.getenv("EMB_BACKEND", "tfidf").lower()
    if want == "dense":
        try:
            return DenseBackend(chunks)
        except Exception as e:  # нет пакета/модели — падаем на tfidf
            print(f"[search] dense backend недоступен ({e}); использую tfidf")
    return TfidfBackend(chunks)


if __name__ == "__main__":
    import json
    from pathlib import Path
    idx = json.loads((Path(__file__).parent / "index.json").read_text("utf-8"))
    be = build_backend(idx)
    print(f"backend={be.name}, чанков={len(idx)}")
    for score, ch in be.search("как устроен RAG", k=3):
        print(f"  {score:.3f}  {ch['source']}::{ch['section']}")
