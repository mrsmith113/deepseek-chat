"""Файловые инструменты для работы с песочницей project/.

Одна ответственность: безопасно читать/искать/писать файлы внутри ROOT —
и отдавать результат в двух видах: как объекты (dict/list) для логики
и как компактный текст для LLM/MCP.

Никаких LLM и сети здесь нет: только файловая система и stdlib.

Главная гарантия — `_safe()`: любой путь резолвится относительно ROOT,
и попытка выйти наружу (`../../etc/passwd`, абсолютный путь, симлинк)
заканчивается ValueError, а не чтением чужого файла.
"""
from __future__ import annotations

import fnmatch
import re
from difflib import unified_diff
from pathlib import Path

ROOT = (Path(__file__).parent / "project").resolve()

# Служебный мусор, который не должен попадать в листинг и поиск.
IGNORE_DIRS = {"__pycache__", ".git", ".venv", "node_modules"}
IGNORE_GLOBS = ("*.pyc", "*.pyo", "*.so")

GREP_LIMIT = 200  # максимум хитов, чтобы не завалить контекст модели


# ------------------------------------------------------------- защита --------
def _safe(rel_path: str) -> Path:
    """Резолвит путь относительно ROOT. ValueError, если он выходит за ROOT.

    Это единственная дверь к файловой системе: все остальные функции
    обязаны ходить через неё. Проверка идёт по уже резолвленному пути,
    поэтому ловятся и `../`, и абсолютные пути, и симлинки наружу.
    """
    if rel_path is None:
        raise ValueError("Пустой путь")
    candidate = (ROOT / str(rel_path)).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"Путь вне песочницы project/: {rel_path}")
    return candidate


def _ignored(p: Path) -> bool:
    """True, если файл — служебный мусор (кэш, .git, скомпилированное)."""
    if any(part in IGNORE_DIRS for part in p.parts):
        return True
    return any(fnmatch.fnmatch(p.name, g) for g in IGNORE_GLOBS)


def _rel(p: Path) -> str:
    """Путь относительно ROOT в posix-виде (одинаково на всех ОС)."""
    return p.relative_to(ROOT).as_posix()


def _is_text(p: Path) -> bool:
    """Грубая проверка «файл текстовый»: читается ли он как UTF-8."""
    try:
        p.read_text(encoding="utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


# ------------------------------------------------------------- чтение --------
def fs_list(subdir: str = ".") -> list[str]:
    """Рекурсивный список файлов внутри subdir — rel-пути от ROOT, отсортировано."""
    base = _safe(subdir)
    if not base.exists():
        raise ValueError(f"Папка не найдена: {subdir}")
    if base.is_file():
        return [_rel(base)]

    files = [_rel(p) for p in base.rglob("*") if p.is_file() and not _ignored(p)]
    return sorted(files)


def fs_read(path: str) -> str:
    """Содержимое файла как текст. ValueError, если файла нет."""
    p = _safe(path)
    if not p.exists():
        raise ValueError(f"Файл не найден: {path}")
    if not p.is_file():
        raise ValueError(f"Это не файл, а папка: {path}")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Файл не текстовый ({path}): {e}") from e


def fs_grep(pattern: str, glob: str = "*") -> list[dict]:
    """Regex-поиск по текстовым файлам, подходящим под glob (регистронезависимо).

    glob сверяется и с именем файла (`*.py`), и с полным rel-путём
    (`docs/*.md`) — что удобнее в конкретном случае, то и сработает.

    Возвращает [{"file": str, "line": int, "text": str}], максимум GREP_LIMIT.
    """
    if not (pattern or "").strip():
        raise ValueError("Пустой поисковый паттерн")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Некорректное регулярное выражение «{pattern}»: {e}") from e

    glob = glob or "*"
    hits: list[dict] = []

    for rel in fs_list("."):
        if not (fnmatch.fnmatch(Path(rel).name, glob) or fnmatch.fnmatch(rel, glob)):
            continue
        p = ROOT / rel
        if not _is_text(p):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if rx.search(line):
                hits.append({"file": rel, "line": i, "text": line.rstrip()})
                if len(hits) >= GREP_LIMIT:
                    return hits
    return hits


# ------------------------------------------------------------- запись --------
def fs_diff(path: str, new_content: str) -> str:
    """Unified diff «что на диске» vs «что предлагается». Пусто — если нет изменений.

    Несуществующий файл трактуется как пустой: получится diff создания.
    """
    p = _safe(path)
    old = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else ""
    if old == new_content:
        return ""

    diff = unified_diff(
        old.splitlines(keepends=True),
        (new_content or "").splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    # Строки без \n в конце (последняя строка файла) склеились бы в кашу.
    return "".join(l if l.endswith("\n") else l + "\n" for l in diff)


def fs_write(path: str, content: str, dry_run: bool = False) -> dict:
    """Пишет файл, предварительно посчитав diff. При dry_run на диск не пишет.

    Возвращает {"path", "created", "changed", "dry_run", "diff"}.
    Родительские папки создаются автоматически.
    """
    p = _safe(path)
    created = not p.exists()
    diff = fs_diff(path, content)
    changed = bool(diff)

    if changed and not dry_run:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    return {"path": path, "created": created, "changed": changed,
            "dry_run": dry_run, "diff": diff}


# ------------------------------------------------------------- рендер --------
def format_grep(hits: list[dict]) -> str:
    """Хиты поиска в привычном виде `file:line: text` + итоговая строка."""
    if not hits:
        return "Совпадений не найдено."
    lines = [f"{h['file']}:{h['line']}: {h['text']}" for h in hits]
    lines.append(f"\nНайдено {len(hits)} совпадений"
                 + (f" (показаны первые {GREP_LIMIT})" if len(hits) >= GREP_LIMIT else ""))
    return "\n".join(lines)


def format_list(files: list[str]) -> str:
    """Список файлов построчно + счётчик."""
    if not files:
        return "Файлов не найдено."
    return "\n".join(files) + f"\n\nВсего файлов: {len(files)}"


if __name__ == "__main__":
    files = fs_list()
    print(f"ROOT: {ROOT}")
    print()
    print(format_list(files))
    print()
    hits = fs_grep(r"def ", glob="*.py")
    print(format_grep(hits[:10]))
