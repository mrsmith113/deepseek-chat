"""Индексатор: документация + код → index.json.

Одна ответственность: собрать чанки из проекта (README, docs/, *.py) и
сохранить их в JSON-индекс без внешней БД. Векторизация (TF-IDF) выполняется
при загрузке в search.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from chunking import chunk_dir

HERE = Path(__file__).parent
INDEX_PATH = HERE / "index.json"


def build_index(root: Path | None = None) -> list[dict]:
    root = root or HERE
    chunks = chunk_dir(root)
    INDEX_PATH.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return chunks


def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return build_index()
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    chunks = build_index()
    docs = sum(1 for c in chunks if c.get("kind") == "doc")
    code = sum(1 for c in chunks if c.get("kind") == "code")
    sources = sorted({c["source"] for c in chunks})
    print(f"Индекс собран: {len(chunks)} чанков "
          f"(doc={docs}, code={code}) из {len(sources)} файлов")
    for s in sources:
        n = sum(1 for c in chunks if c["source"] == s)
        print(f"  {s}: {n}")
    print(f"Сохранено → {INDEX_PATH.name}")
