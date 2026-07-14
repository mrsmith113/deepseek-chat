"""Парсер unified diff → структура изменений.

Одна ответственность: из текста `git diff` вытащить, что нужно ревьюеру:
  * список изменённых файлов,
  * добавленные строки (с номерами в новом файле) — их и ревьюим,
  * язык файла (для выбора эвристик).

Не зависит от git — принимает готовый текст diff (из git_tools.pr_diff,
из файла *.diff или из stdin). Это делает пайплайн тестируемым офлайн.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".go": "go", ".java": "java", ".rb": "ruby", ".rs": "rust",
    ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".sh": "shell",
}


@dataclass
class AddedLine:
    lineno: int   # номер строки в НОВОМ файле
    text: str     # содержимое (без ведущего '+')


@dataclass
class FileDiff:
    path: str
    lang: str = "text"
    added: list[AddedLine] = field(default_factory=list)
    raw_hunks: list[str] = field(default_factory=list)

    @property
    def added_text(self) -> str:
        return "\n".join(a.text for a in self.added)


def _lang_of(path: str) -> str:
    for ext, lang in _LANG.items():
        if path.endswith(ext):
            return lang
    return "text"


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Разбирает unified diff в список FileDiff с добавленными строками."""
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    new_lineno = 0
    hunk_buf: list[str] = []

    def close_hunk():
        if cur and hunk_buf:
            cur.raw_hunks.append("\n".join(hunk_buf))

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            close_hunk()
            hunk_buf = []
            cur = None
            continue
        if line.startswith("+++ "):
            # +++ b/path  или  +++ /dev/null (удаление)
            path = line[4:].strip()
            path = path[2:] if path.startswith(("a/", "b/")) else path
            if path == "/dev/null":
                cur = None
                continue
            cur = FileDiff(path=path, lang=_lang_of(path))
            files.append(cur)
            continue
        if line.startswith("--- "):
            continue
        m = _HUNK.match(line)
        if m:
            close_hunk()
            hunk_buf = [line]
            new_lineno = int(m.group(1))
            continue
        if cur is None:
            continue
        hunk_buf.append(line)
        if line.startswith("+") and not line.startswith("+++"):
            cur.added.append(AddedLine(new_lineno, line[1:]))
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # удалённая строка — номер в новом файле не растёт
        else:
            new_lineno += 1  # контекст

    close_hunk()
    return files


def summary(files: list[FileDiff]) -> str:
    parts = [f"{f.path} (+{len(f.added)} строк, {f.lang})" for f in files]
    return "Изменённые файлы:\n" + "\n".join(f"  • {p}" for p in parts)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    text = (Path(sys.argv[1]).read_text("utf-8") if len(sys.argv) > 1
            else sys.stdin.read())
    fs = parse_diff(text)
    print(summary(fs))
    for f in fs[:3]:
        print(f"--- {f.path} ---")
        for a in f.added[:5]:
            print(f"  +{a.lineno}: {a.text}")
