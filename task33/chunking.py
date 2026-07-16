"""Чанкинг базы знаний поддержки (markdown) по секциям.

Одна ответственность: превратить docs/*.md в список чанков с
метаданными. Каждый чанк = одна секция (заголовок ## / ###) или её часть,
если секция слишком длинная.

Индексируем только документацию (kind="doc"): CRM-данные приходят не через
RAG, а напрямую через crm_tools/MCP — их незачем размывать в эмбеддингах.
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_CHARS = 900     # мягкий предел длины чанка; длинные секции режем по абзацам
MIN_BODY_CHARS = 40  # чанк из одного заголовка без тела в индексе бесполезен


def _strip_headings(text: str) -> str:
    """Текст без markdown-заголовков — чтобы оценить, есть ли в чанке тело."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#")).strip()


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
    raw = path.read_text(encoding="utf-8", errors="ignore")
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
        # Заголовок-«сирота» (только H1 документа, без тела) — не ответ, а
        # обложка. В индексе он лишь мешает: короткий чанк легко выигрывает
        # у длинного по косинусу, а сказать ему нечего.
        if len(_strip_headings(text)) < MIN_BODY_CHARS:
            return
        for piece in _split_long(text):
            # Заголовок секции кладём в текст чанка, а не только в метаданные:
            # иначе вопрос «как выгрузить документы» не найдёт секцию с ровно
            # таким названием — заголовки были бы невидимы для поиска.
            body_text = piece if section == "intro" else f"{section}\n{piece}"
            chunks.append({"source": path.name, "title": doc_title,
                           "section": section, "text": body_text, "kind": "doc"})

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
    """Собирает чанки из docs/*.md. Проставляет chunk_id.

    Индексируем только docs/ — это база знаний продукта (product/faq/
    troubleshooting). README описывает сам пайплайн task33 и в ответах
    поддержки не нужен: иначе ассистент цитирует в «Источниках» собственный
    пример вывода.
    """
    files: list[Path] = []
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
    sources = sorted({c["source"] for c in cs})
    print(f"Документов: {len(sources)}, чанков: {len(cs)}")
    for c in cs[:4]:
        print(f"  [{c['chunk_id']}] {c['source']} :: {c['section']}"
              f" — {c['text'][:60]}...")
