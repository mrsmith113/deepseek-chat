"""CLI точка входа AI-ревью — то, что запускает GitHub Action и человек.

Источник diff (по приоритету):
  --diff FILE   — готовый *.diff файл (демо/тесты, офлайн);
  --base REF    — git diff BASE...HEAD (реальный PR в CI);
  (без флагов)  — git diff рабочего дерева (локальная проверка).

Примеры:
    python review.py --diff samples/sample_pr.diff
    python review.py --base origin/master --out review.md
    python review.py --no-llm                 # только эвристики+RAG
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import git_tools
from reviewer import review

HERE = Path(__file__).parent


def get_diff(args) -> str:
    if args.diff:
        return Path(args.diff).read_text("utf-8")
    if not sys.stdin.isatty() and not args.base:
        data = sys.stdin.read()
        if data.strip():
            return data
    return git_tools.pr_diff(base=args.base, head=args.head)


def main() -> None:
    ap = argparse.ArgumentParser(description="AI code review для PR (task32)")
    ap.add_argument("--diff", help="путь к готовому .diff файлу")
    ap.add_argument("--base", help="базовая ветка/ref для diff BASE...HEAD")
    ap.add_argument("--head", default="HEAD", help="head ref (по умолч. HEAD)")
    ap.add_argument("--out", help="куда записать ревью (markdown)")
    ap.add_argument("--no-llm", action="store_true",
                    help="без LLM — только статический анализ + RAG")
    args = ap.parse_args()

    diff = get_diff(args)
    if not diff.strip():
        print("Diff пуст — нечего ревьюить.")
        return

    text = review(diff, use_llm=not args.no_llm)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Ревью записано → {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
