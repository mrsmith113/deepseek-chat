"""Вспомогательные функции общего назначения."""

import re
import unicodedata


def chunked(seq, n):
    """Разбивает последовательность на куски по n элементов.

    Аргументы:
        seq: список или другая последовательность.
        n: размер куска, должен быть больше нуля.

    Возвращает:
        список списков.
    """
    if n <= 0:
        raise ValueError("Размер куска должен быть положительным")

    return [list(seq[i:i + n]) for i in range(0, len(seq), n)]


def slugify(text):
    """Превращает произвольный текст в slug для URL.

    Аргументы:
        text: исходная строка.

    Возвращает:
        строку из латиницы, цифр и дефисов.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slug.strip("-")
