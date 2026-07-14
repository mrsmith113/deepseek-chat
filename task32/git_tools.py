"""Живой git-контекст и diff PR.

Достаёт из репозитория данные, которые нужны ревьюеру:
  * git_branch      — текущая ветка,
  * git_files       — файлы под контролем,
  * diff_stat       — сводка изменений (--stat),
  * pr_diff         — полный unified diff PR: <base>...<head>.

Переиспользует подход git_tools.py из task31.1, добавляет получение diff
относительно базовой ветки (для GitHub Action на pull_request).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Репозиторий — родитель папки task32 (корень GIT/).
REPO = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                             text=True, timeout=30)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return f"[git error] {e}"


def git_branch() -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"]) or "(unknown)"


def git_files(limit: int = 60) -> str:
    files = [f for f in _run(["ls-files"]).splitlines() if f]
    head = files[:limit]
    extra = len(files) - len(head)
    tail = f"\n… и ещё {extra} файлов" if extra > 0 else ""
    return "\n".join(head) + tail


def diff_stat(base: str | None = None, head: str = "HEAD") -> str:
    args = ["diff", "--stat"]
    args += [f"{base}...{head}"] if base else []
    text = _run(args)
    return text or "(изменений нет)"


def pr_diff(base: str | None = None, head: str = "HEAD") -> str:
    """Полный unified diff. Если base задан — diff базы и head (для PR).

    base=None → diff рабочего дерева (локальный режим / незакоммиченное).
    """
    args = ["diff", "--unified=3", "--no-color"]
    if base:
        args.append(f"{base}...{head}")
    return _run(args)


if __name__ == "__main__":
    print("branch:", git_branch())
    print("--- diff --stat ---")
    print(diff_stat())
