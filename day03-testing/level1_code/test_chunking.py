"""Unit + integration тесты чанкинга — task33/chunking.py.

Проверяем: разбиение по секциям, отсев «сирот»-заголовков, вставку
названия секции в текст чанка, нарезку длинных секций, сквозной chunk_id.
"""
import chunking
from chunking import _split_long, _strip_headings, chunk_markdown, chunk_dir


# ---------- чистые helper'ы ----------

def test_strip_headings_removes_markdown_headers():
    text = "# Заголовок\nтело строки\n## Подзаголовок\nещё тело"
    stripped = _strip_headings(text)
    assert "Заголовок" not in stripped
    assert "тело строки" in stripped
    assert "ещё тело" in stripped


def test_split_long_keeps_short_intact():
    assert _split_long("короткий текст", limit=900) == ["короткий текст"]


def test_split_long_splits_by_paragraphs():
    para = "абзац " * 100          # ~600 символов
    text = para + "\n\n" + para     # ~1200 → две части
    parts = _split_long(text, limit=900)
    assert len(parts) == 2
    assert all(len(p) <= 900 for p in parts)


# ---------- chunk_markdown ----------

def _write(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


def test_doc_title_from_h1(tmp_path):
    f = _write(tmp_path, "faq.md",
               "# База знаний FAQ\n\n## Возврат\nКак оформить возврат товара в течение 14 дней.")
    chunks = chunk_markdown(f)
    assert chunks, "должен быть хотя бы один чанк"
    assert all(c["title"] == "База знаний FAQ" for c in chunks)


def test_orphan_heading_is_skipped(tmp_path):
    # Только H1 без тела — «обложка», в индекс не попадает.
    f = _write(tmp_path, "cover.md", "# Просто заголовок без тела\n")
    assert chunk_markdown(f) == []


def test_section_name_injected_into_text(tmp_path):
    f = _write(tmp_path, "doc.md",
               "# Док\n\n## Оплата\nПринимаем карты и СБП, оплата проходит мгновенно и надёжно.")
    chunks = chunk_markdown(f)
    pay = [c for c in chunks if c["section"] == "Оплата"]
    assert pay, "секция Оплата должна существовать"
    # Название секции добавлено в начало текста чанка (для поиска по заголовку)
    assert pay[0]["text"].startswith("Оплата")


def test_metadata_fields_present(tmp_path):
    f = _write(tmp_path, "meta.md",
               "# Т\n\n## Раздел\nДостаточно длинное тело секции для прохождения порога MIN_BODY_CHARS.")
    c = chunk_markdown(f)[0]
    for key in ("source", "title", "section", "text", "kind"):
        assert key in c
    assert c["source"] == "meta.md"
    assert c["kind"] == "doc"


def test_long_section_is_split(tmp_path):
    body = ("Очень длинный абзац поддержки. " * 40)  # ~1200 символов
    f = _write(tmp_path, "long.md", f"# Д\n\n## Большая\n{body}\n\n{body}")
    chunks = [c for c in chunk_markdown(f) if c["section"] == "Большая"]
    assert len(chunks) >= 2


# ---------- chunk_dir (integration) ----------

def test_chunk_dir_assigns_sequential_ids(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text(
        "# A\n\n## S1\nТело первой секции достаточной длины для индекса поддержки.",
        encoding="utf-8")
    (docs / "b.md").write_text(
        "# B\n\n## S2\nТело второй секции достаточной длины для индекса поддержки.",
        encoding="utf-8")
    chunks = chunk_dir(tmp_path)
    ids = [c["chunk_id"] for c in chunks]
    assert ids == list(range(len(chunks)))   # сквозная нумерация без дыр
    assert len(chunks) >= 2


def test_chunk_dir_empty_when_no_docs(tmp_path):
    assert chunk_dir(tmp_path) == []
