"""Офлайн-эвристики code review (статические проверки без LLM).

Зачем: пайплайн обязан выдавать ревью ДАЖЕ когда LLM недоступна
(нет ключа DeepSeek, лежит Ollama). Эти правила ловят частые проблемы по
добавленным строкам diff и гарантируют непустой полезный результат.
Когда LLM доступна — находки эвристик подмешиваются как надёжная база.

Каждая находка: (severity, category, path:line, message).
categories: bug | arch | rec  (баг | архитектура | рекомендация).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from diff_parser import FileDiff


@dataclass
class Finding:
    severity: str   # high | medium | low
    category: str   # bug | arch | rec
    path: str
    line: int
    message: str

    def render(self) -> str:
        icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[self.severity]
        return f"{icon} `{self.path}:{self.line}` — {self.message}"


# (регэксп, severity, category, сообщение) — общие для многих языков
_GENERIC = [
    (re.compile(r"(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{6,}|['\"]sk_(?:live|test)_\w+",
                re.IGNORECASE),
     "high", "bug", "Похоже на захардкоженный секрет — вынести в переменную окружения"),
    (re.compile(r"\bTODO|FIXME|XXX\b"),
     "low", "rec", "Незакрытый TODO/FIXME в новом коде"),
    (re.compile(r"\bhttp://"),
     "low", "rec", "Незащищённый http:// — по возможности использовать https"),
    (re.compile(r".{121,}"),
     "low", "rec", "Строка длиннее 120 символов — тяжело читать"),
]

_PY = [
    (re.compile(r"except\s*:|except\s+Exception\s*:"),
     "medium", "bug", "Слишком широкий except — глотает ошибки, ловить конкретные исключения"),
    (re.compile(r"\beval\(|\bexec\("),
     "high", "bug", "eval/exec на входных данных — риск инъекции кода"),
    (re.compile(r"==\s*None|!=\s*None"),
     "low", "rec", "Сравнение с None через ==; использовать `is None` / `is not None`"),
    (re.compile(r"def\s+\w+\([^)]*=\s*(\[\]|\{\})"),
     "medium", "bug", "Мутабельный аргумент по умолчанию ([]/{}) — общий стейт между вызовами"),
    (re.compile(r"\bprint\("),
     "low", "arch", "print() в коде — для прод-логики использовать logging"),
    (re.compile(r"\bimport\s+\*"),
     "medium", "arch", "Импорт * засоряет namespace и ломает статический анализ"),
    (re.compile(r"subprocess\.(?:run|call|Popen)\([^)]*shell\s*=\s*True"),
     "high", "bug", "subprocess с shell=True — риск shell-инъекции"),
    (re.compile(r"assert\s"),
     "low", "rec", "assert выключается при python -O; для валидации не полагаться на него"),
]

_JS = [
    (re.compile(r"\bvar\s+\w"),
     "low", "rec", "var — предпочесть let/const"),
    (re.compile(r"==(?!=)|!=(?!=)"),
     "medium", "bug", "Нестрогое сравнение ==/!=; использовать ===/!=="),
    (re.compile(r"console\.log\("),
     "low", "arch", "console.log в коде — убрать перед мержем"),
    (re.compile(r"\beval\("),
     "high", "bug", "eval() — риск инъекции"),
]

_BY_LANG = {"python": _PY, "javascript": _JS, "typescript": _JS}


def scan_file(fd: FileDiff) -> list[Finding]:
    rules = _GENERIC + _BY_LANG.get(fd.lang, [])
    out: list[Finding] = []
    for al in fd.added:
        line = al.text
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*")):
            # комментарии проверяем только на секреты/TODO (generic)
            active = _GENERIC
        else:
            active = rules
        for rx, sev, cat, msg in active:
            if rx.search(line):
                out.append(Finding(sev, cat, fd.path, al.lineno, msg))
    # архитектурная эвристика на уровне файла: большой diff
    if len(fd.added) > 150:
        out.append(Finding("medium", "arch", fd.path, 0,
                           f"Крупное изменение (+{len(fd.added)} строк) — "
                           "возможно, стоит разбить PR на части"))
    return out


def scan(files: list[FileDiff]) -> list[Finding]:
    out: list[Finding] = []
    for fd in files:
        out.extend(scan_file(fd))
    # порядок по severity
    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (order[f.severity], f.path, f.line))
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    from diff_parser import parse_diff
    text = (Path(sys.argv[1]).read_text("utf-8") if len(sys.argv) > 1
            else sys.stdin.read())
    for f in scan(parse_diff(text)):
        print(f.render(), f"[{f.category}]")
