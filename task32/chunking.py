"""Чанкинг источников для RAG: документация (markdown) + код (python).

Задание требует RAG «документация + код», поэтому индексируем оба вида:
  * markdown — по секциям (заголовки ## / ###), как в task31.1;
  * python   — по определениям (def / class верхнего уровня) + модульный intro.

Одна ответственность: превратить файлы проекта в список чанков с метаданными
(source, title, section, chunk_id).
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_CHARS = 900  # мягкий предел длины чанка

# что НЕ индексируем (артефакты, окружения, сам ревьюер-инструмент опционально)
SKIP_DIRS = {".git", "__pycache__", ".github", "node_modules", ".venv", "venv"}
SKIP_FILES = {"index.json", "review.md"}  # артефакты ревьюера не индексируем


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
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


# --------------------------------------------------------------- markdown ----
def chunk_markdown(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()

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
                           "section": section, "text": piece, "kind": "doc"})

    for ln in lines:
        m = re.match(r"^#{2,3}\s+(.+)", ln)
        if m:
            flush()
            body = []
            section = m.group(1).strip()
        else:
            body.append(ln)
    flush()
    return chunks


# ------------------------------------------------------------------ python ---
_DEF = re.compile(r"^(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)")


def chunk_python(path: Path) -> list[dict]:
    """Режет .py по определениям верхнего уровня. Каждый def/class — чанк."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()

    chunks: list[dict] = []
    section = "module"
    body: list[str] = []

    def flush():
        text = "\n".join(body).strip()
        if not text:
            return
        for piece in _split_long(text):
            chunks.append({"source": path.name, "title": path.stem,
                           "section": section, "text": piece, "kind": "code"})

    for ln in lines:
        m = _DEF.match(ln)  # только верхний уровень (без отступа)
        if m:
            flush()
            body = [ln]
            section = f"{m.group(1)} {m.group(2)}"
        else:
            body.append(ln)
    flush()
    return chunks


# --------------------------------------------------------------- collect -----
def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix in (".md", ".py"):
            yield p


def chunk_dir(root: Path) -> list[dict]:
    """Собирает чанки со всех .md и .py под root. Проставляет chunk_id."""
    all_chunks: list[dict] = []
    for f in _iter_files(root):
        if f.suffix == ".md":
            all_chunks.extend(chunk_markdown(f))
        elif f.suffix == ".py":
            all_chunks.extend(chunk_python(f))
    for i, c in enumerate(all_chunks):
        c["chunk_id"] = i
    return all_chunks


if __name__ == "__main__":
    here = Path(__file__).parent
    cs = chunk_dir(here)
    docs = sum(1 for c in cs if c["kind"] == "doc")
    code = sum(1 for c in cs if c["kind"] == "code")
    print(f"Чанков: {len(cs)} (doc={docs}, code={code})")
    for c in cs[:4]:
        print(f"  [{c['chunk_id']}] {c['kind']:4} {c['source']} :: "
              f"{c['section']} — {c['text'][:50]}...")
