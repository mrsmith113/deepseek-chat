"""
Поиск по JSON-индексу с косинусным сходством.
"""

import json
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from sentence_transformers import SentenceTransformer

INDEX_DIR = os.path.join(os.path.dirname(__file__), "index")
MODEL_NAME = "ai-sage/Giga-Embeddings-instruct"

_model = None
_indexes = {}


def get_model():
    global _model
    if _model is None:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=device)
    return _model


def load_index(strategy: str) -> list[dict]:
    global _indexes
    if strategy not in _indexes:
        path = os.path.join(INDEX_DIR, f"index_{strategy}.json")
        with open(path, encoding="utf-8") as f:
            _indexes[strategy] = json.load(f)
    return _indexes[strategy]


def cosine_search(query: str, strategy: str, top_k: int = 5) -> list[dict]:
    model = get_model()
    query_vec = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]

    index = load_index(strategy)
    scores = []
    for chunk in index:
        vec = np.array(chunk["embedding"])
        score = float(np.dot(query_vec, vec))
        scores.append((score, chunk))

    scores.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, chunk in scores[:top_k]:
        results.append({
            "score": round(score, 4),
            "title": chunk["title"],
            "date": chunk["date"],
            "section": chunk["section"],
            "chunk_id": chunk["chunk_id"],
            "text_preview": chunk["text"][:200],
            "char_count": chunk["char_count"],
        })
    return results


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "как перевести деньги в Китай"
    strategy = "struct"

    print(f'Поиск: "{query}" (strategy={strategy})\n')
    results = cosine_search(query, strategy, top_k=3)
    for r in results:
        print(f"[{r['score']}] {r['title']} — {r['section']}")
        print(f"  {r['text_preview']}")
        print()
