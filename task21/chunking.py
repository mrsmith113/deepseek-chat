"""
Две стратегии чанкинга для Task 21.

Strategy 1: Fixed-size — режем текст на куски фиксированного размера с перекрытием.
Strategy 2: Structure-based — режем по заголовкам ## (структура документа).
"""

import re


def extract_text(md_text: str) -> tuple[str, str, str]:
    """Извлекает заголовок, дату и основной текст (без <details> транскрипта)."""
    title = re.search(r"^# (.+)$", md_text, re.MULTILINE)
    title = title.group(1).strip() if title else "Без заголовка"

    date = re.search(r"\*\*Дата:\*\* (.+)$", md_text, re.MULTILINE)
    date = date.group(1).strip() if date else ""

    # Берём только обработанную часть (до <details>)
    details_pos = md_text.find("<details>")
    body = md_text[:details_pos] if details_pos != -1 else md_text

    # Убираем метаданные (первый блок до первого ##)
    first_section = body.find("\n## ")
    if first_section != -1:
        body = body[first_section:]

    return title, date, body.strip()


# ─── Strategy 1: Fixed-size chunking ─────────────────────────────────────────

def chunk_fixed(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """
    Режет текст на куски фиксированного размера с перекрытием.
    Простой, универсальный, но может разрывать смысловые блоки.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks


def strategy_fixed(title: str, date: str, filename: str, body: str,
                   chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    """Возвращает список чанков с метаданными (стратегия 1: fixed-size)."""
    raw_chunks = chunk_fixed(body, chunk_size, overlap)
    result = []
    for i, text in enumerate(raw_chunks):
        result.append({
            "chunk_id": f"{filename}__fixed_{i}",
            "strategy": "fixed",
            "source": filename,
            "title": title,
            "date": date,
            "section": f"chunk_{i+1}_of_{len(raw_chunks)}",
            "text": text,
            "char_count": len(text),
        })
    return result


# ─── Strategy 2: Structure-based chunking ────────────────────────────────────

def chunk_struct(body: str) -> list[tuple[str, str]]:
    """
    Режет текст по заголовкам ## (разделам документа).
    Сохраняет смысловую целостность, но размер чанков непредсказуем.
    """
    sections = re.split(r"\n(?=## )", body)
    result = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Заголовок секции
        header_match = re.match(r"^## (.+)$", section, re.MULTILINE)
        header = header_match.group(1).strip() if header_match else "Введение"
        result.append((header, section))
    return result


def strategy_struct(title: str, date: str, filename: str, body: str) -> list[dict]:
    """Возвращает список чанков с метаданными (стратегия 2: structure-based)."""
    sections = chunk_struct(body)
    result = []
    for i, (section_title, text) in enumerate(sections):
        result.append({
            "chunk_id": f"{filename}__struct_{i}",
            "strategy": "struct",
            "source": filename,
            "title": title,
            "date": date,
            "section": section_title,
            "text": text,
            "char_count": len(text),
        })
    return result
