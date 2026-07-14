"""Чанкинг markdown-документации по секциям (заголовкам).

Одна ответственность: превратить .md файлы в список чанков с метаданными.
Каждый чанк = одна секция (по заголовку ## / ###) или её часть, если секция
слишком длинная.
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_CHARS = 900  # мягкий предел длины чанка; длинные секции режем по абзацам


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Режет длинный текст по абзацам, не разрывая слова."""
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > limit and buf:
            parts.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        parts.append(buf.strip())
    return parts


def chunk_markdown(path: Path) -> list[dict]:
    """Разбивает один markdown-файл на чанки с метаданными."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Заголовок документа = первый H1, иначе имя файла.
    doc_title = path.stem
    for ln in lines:
        m = re.match(r"^#\s+(.+)", ln)
        if m:
            doc_title = m.group(1).strip()
            break

    chunks: list[dict] = []
    section = "intro"
    body: list[str] = []

    def flush():
        text = "\n".join(body).strip()
        if not text:
            return
        for piece in _split_long(text):
            chunks.append({"source": path.name, "title": doc_title,
                           "section": section, "text": piece})

    for ln in lines:
        m = re.match(r"^#{2,3}\s+(.+)", ln)  # секции по ## и ###
        if m:
            flush()
            body = []
            section = m.group(1).strip()
        else:
            body.append(ln)
    flush()
    return chunks


def chunk_dir(root: Path) -> list[dict]:
    """Собирает чанки со всех .md в README и docs/. Проставляет chunk_id."""
    files: list[Path] = []
    readme = root / "README.md"
    if readme.exists():
        files.append(readme)
    docs = root / "docs"
    if docs.exists():
        files.extend(sorted(docs.glob("*.md")))

    all_chunks: list[dict] = []
    for f in files:
        all_chunks.extend(chunk_markdown(f))
    for i, c in enumerate(all_chunks):
        c["chunk_id"] = i
    return all_chunks


if __name__ == "__main__":
    here = Path(__file__).parent
    cs = chunk_dir(here)
    print(f"Файлов документации обработано, чанков: {len(cs)}")
    for c in cs[:3]:
        print(f"  [{c['chunk_id']}] {c['source']} :: {c['section']}"
              f" — {c['text'][:60]}...")
