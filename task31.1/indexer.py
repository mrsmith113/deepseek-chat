"""Индексатор документации → index.json.

Одна ответственность: собрать чанки из README+docs и сохранить их в JSON-индекс
(без внешней БД, как в task21). Векторизация происходит при загрузке в search.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from chunking import chunk_dir

HERE = Path(__file__).parent
INDEX_PATH = HERE / "index.json"


def build_index() -> list[dict]:
    chunks = chunk_dir(HERE)
    INDEX_PATH.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return chunks


if __name__ == "__main__":
    chunks = build_index()
    sources = sorted({c["source"] for c in chunks})
    print(f"Индекс собран: {len(chunks)} чанков из {len(sources)} документов")
    for s in sources:
        n = sum(1 for c in chunks if c["source"] == s)
        print(f"  {s}: {n} чанков")
    print(f"Сохранено → {INDEX_PATH.name}")
