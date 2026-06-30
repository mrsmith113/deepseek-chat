"""
Task 21 — Индексация документов.

Читает 10 MD-файлов из documents/, применяет 2 стратегии чанкинга,
генерирует эмбеддинги (GigaEmbeddings), сохраняет в index/index_fixed.json
и index/index_struct.json.
"""

import os
import json
import glob
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from sentence_transformers import SentenceTransformer

from chunking import extract_text, strategy_fixed, strategy_struct

DOCS_DIR = os.path.join(os.path.dirname(__file__), "documents")
INDEX_DIR = os.path.join(os.path.dirname(__file__), "index")
MODEL_NAME = "ai-sage/Giga-Embeddings-instruct"
DEVICE = "cuda"


def load_documents() -> list[dict]:
    docs = []
    for path in sorted(glob.glob(os.path.join(DOCS_DIR, "*.md"))):
        filename = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        title, date, body = extract_text(text)
        docs.append({"filename": filename, "title": title, "date": date, "body": body})
    return docs


def build_chunks(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    fixed_chunks, struct_chunks = [], []
    for doc in docs:
        fixed_chunks.extend(strategy_fixed(doc["title"], doc["date"], doc["filename"], doc["body"]))
        struct_chunks.extend(strategy_struct(doc["title"], doc["date"], doc["filename"], doc["body"]))
    return fixed_chunks, struct_chunks


def embed_chunks(model, chunks: list[dict]) -> np.ndarray:
    texts = [c["text"] for c in chunks]
    return model.encode(texts, batch_size=16, show_progress_bar=True,
                        normalize_embeddings=True, convert_to_numpy=True)


def save_index(chunks: list[dict], embeddings: np.ndarray, path: str):
    data = []
    for chunk, vec in zip(chunks, embeddings):
        entry = dict(chunk)
        entry["embedding"] = vec.tolist()
        data.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Сохранено {len(data)} чанков → {path}")


def main():
    os.makedirs(INDEX_DIR, exist_ok=True)

    print("Загружаю документы...")
    docs = load_documents()
    print(f"  Документов: {len(docs)}")

    print("\nСоздаю чанки...")
    fixed_chunks, struct_chunks = build_chunks(docs)
    print(f"  Strategy 1 (fixed):  {len(fixed_chunks)} чанков")
    print(f"  Strategy 2 (struct): {len(struct_chunks)} чанков")

    # Статистика размеров
    fixed_sizes = [c["char_count"] for c in fixed_chunks]
    struct_sizes = [c["char_count"] for c in struct_chunks]
    print(f"\n  Fixed  — avg: {sum(fixed_sizes)//len(fixed_sizes)} chars, "
          f"min: {min(fixed_sizes)}, max: {max(fixed_sizes)}")
    print(f"  Struct — avg: {sum(struct_sizes)//len(struct_sizes)} chars, "
          f"min: {min(struct_sizes)}, max: {max(struct_sizes)}")

    print(f"\nЗагружаю модель {MODEL_NAME}...")
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=device)
    print(f"  Модель загружена на {device}")

    print("\nГенерирую эмбеддинги (Strategy 1 — fixed)...")
    fixed_emb = embed_chunks(model, fixed_chunks)

    print("\nГенерирую эмбеддинги (Strategy 2 — struct)...")
    struct_emb = embed_chunks(model, struct_chunks)

    print("\nСохраняю индексы...")
    save_index(fixed_chunks, fixed_emb, os.path.join(INDEX_DIR, "index_fixed.json"))
    save_index(struct_chunks, struct_emb, os.path.join(INDEX_DIR, "index_struct.json"))

    print("\n✅ Индексация завершена!")
    print(f"   index/index_fixed.json  — {len(fixed_chunks)} чанков")
    print(f"   index/index_struct.json — {len(struct_chunks)} чанков")


if __name__ == "__main__":
    main()
