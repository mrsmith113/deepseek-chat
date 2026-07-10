#!/usr/bin/env python3
"""
Task 28 — Полностью локальный RAG-пайплайн
Retrieval: GigaEmbeddings + Qdrant (youtube_rag)
Generation: Qwen3 14B через Ollama
Всё работает без интернета.
"""

import time
import requests
import warnings
warnings.filterwarnings("ignore")

QDRANT_URL  = "http://localhost:6333"
OLLAMA_URL  = "http://localhost:11434/api/generate"
COLLECTION  = "youtube_rag"
MODEL       = "qwen3:14b"
MODEL_NAME  = "ai-sage/Giga-Embeddings-instruct"

# Отключаем прокси для локальных запросов (v2rayN + ALL_PROXY в env)
_http = requests.Session()
_http.trust_env = False

_embed_model = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"  [embed] Загружаю GigaEmbeddings на {device}...")
        _embed_model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=device)
    return _embed_model


def embed(text: str) -> list[float]:
    model = get_embed_model()
    vec = model.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
    return vec.tolist()


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Поиск в Qdrant по эмбеддингу вопроса."""
    vec = embed(query)
    resp = _http.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
        json={"vector": vec, "limit": top_k, "with_payload": True},
        timeout=30,
    )
    resp.raise_for_status()
    hits = resp.json().get("result", [])
    return [
        {
            "score": round(h["score"], 4),
            "title": h["payload"].get("title", ""),
            "text":  h["payload"].get("text", ""),
            "source": h["payload"].get("source", ""),
        }
        for h in hits
    ]


def generate_local(question: str, context: str) -> tuple[str, float]:
    """Генерация ответа через Qwen3 14B (Ollama)."""
    prompt = f"""Ты эксперт по ВЭД и таможенному оформлению. Отвечай только на основе предоставленного контекста.
Если ответа в контексте нет — так и скажи.

КОНТЕКСТ:
{context}

ВОПРОС: {question}

ОТВЕТ:"""

    t0 = time.time()
    resp = _http.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_predict": 600, "temperature": 0.3},
    }, timeout=300)
    resp.raise_for_status()
    elapsed = round(time.time() - t0, 1)
    answer = resp.json().get("response", "").strip()
    return answer, elapsed


def ask(question: str, top_k: int = 5, verbose: bool = True) -> dict:
    """Полный RAG-пайплайн: вопрос → retrieve → generate."""
    if verbose:
        print(f"\n🔍 Retrieval...")
    t_ret = time.time()
    docs = retrieve(question, top_k=top_k)
    ret_time = round(time.time() - t_ret, 1)

    context = "\n\n".join(
        f"[{d['title']}]\n{d['text'][:500]}" for d in docs
    )

    if verbose:
        print(f"  Найдено {len(docs)} чанков за {ret_time}с")
        print(f"🤖 Генерация (Qwen3 14B)...")

    answer, gen_time = generate_local(question, context)

    return {
        "question": question,
        "answer": answer,
        "sources": docs,
        "retrieval_time": ret_time,
        "generation_time": gen_time,
        "total_time": round(ret_time + gen_time, 1),
        "model": f"Qwen3 14B (local) + Qdrant {COLLECTION}",
    }


def print_result(result: dict):
    print(f"\n{'='*60}")
    print(f"Вопрос: {result['question']}")
    print(f"Модель: {result['model']}")
    print(f"Время:  retrieval {result['retrieval_time']}с | gen {result['generation_time']}с | итого {result['total_time']}с")
    print(f"{'='*60}")
    print(result["answer"])
    print(f"\n📚 Источники ({len(result['sources'])}):")
    for i, s in enumerate(result["sources"][:3], 1):
        print(f"  {i}. [{s['score']}] {s['title']}")


if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Что такое нотификация ФСБ?"
    result = ask(question)
    print_result(result)
