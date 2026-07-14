"""Живой git-контекст проекта.

Единая логика, которую переиспользуют и MCP-сервер (mcp_server.py), и ассистент
(assistant.py). Работает с репозиторием, в котором лежит task32.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Репозиторий — родитель папки task32 (корень GIT/).
REPO = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                             text=True, timeout=15)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return f"[git error] {e}"


def git_branch() -> str:
    """Текущая ветка репозитория (минимальное требование задания)."""
    return _run(["rev-parse", "--abbrev-ref", "HEAD"]) or "(unknown)"


def git_files(limit: int = 60) -> str:
    """Список файлов под контролем git (обрезаем для читаемости)."""
    text = _run(["ls-files"])
    files = [f for f in text.splitlines() if f]
    head = files[:limit]
    extra = len(files) - len(head)
    tail = f"\n… и ещё {extra} файлов" if extra > 0 else ""
    return "\n".join(head) + tail


def git_diff(staged: bool = False) -> str:
    """Unified diff рабочего дерева (или staged-изменений)."""
    args = ["diff", "--stat"]
    if staged:
        args.insert(1, "--staged")
    text = _run(args)
    return text or "(изменений нет)"


def git_context() -> str:
    """Короткая сводка для подмешивания в ответ ассистента."""
    return (f"Ветка: {git_branch()}\n"
            f"Изменения:\n{git_diff()}")


if __name__ == "__main__":
    print("branch:", git_branch())
    print("---files---")
    print(git_files(limit=10))
    print("---diff---")
    print(git_diff())
