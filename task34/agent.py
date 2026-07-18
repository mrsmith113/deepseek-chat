"""Мозг ассистента: ReAct-агент над файловыми инструментами.

Идея домашки: задача ставится на уровне ЦЕЛИ («приведи доку в соответствие
с кодом»), а не на уровне действия («открой файл X»). Какие инструменты звать,
в каком порядке и когда остановиться — решает сам ассистент.

Пайплайн одного шага:
    цель + история → LLM → JSON {thought, action, action_input}
                          → выполняем инструмент из TOOLS
                          → observation (обрезанный) уходит в историю
                          → следующий шаг… пока не {final_answer} или max_steps

Два режима, один и тот же интерфейс:
  * LLM-режим     — план строит модель (llm.chat: DeepSeek → Ollama);
  * офлайн-режим  — llm.chat вернул None: исполняем ДЕТЕРМИНИРОВАННЫЙ план
                    из offline_plan(). Те же самые инструменты, те же шаги,
                    те же observation — просто «мышление» зашито в код.

Офлайн-режим — не заглушка, а гарантия воспроизводимости: домашка целиком
проходит без сети и без API-ключей, результат побайтно одинаков от прогона
к прогону.

Разбор Python — только через `ast`, никаких регулярок по коду.
"""
from __future__ import annotations

import ast
import json

import fs_tools
import llm

OBS_LIMIT = 4000  # максимум символов observation, чтобы не разорвать контекст
OBS_ECHO = 200    # сколько символов observation печатать в verbose-логе


# ================================================================ инструменты =
def _t_fs_list(subdir: str = ".") -> tuple[list, str]:
    files = fs_tools.fs_list(subdir or ".")
    return files, fs_tools.format_list(files)


def _t_fs_read(path: str) -> tuple[str, str]:
    text = fs_tools.fs_read(path)
    return text, text


def _t_fs_grep(pattern: str, glob: str = "*") -> tuple[list, str]:
    hits = fs_tools.fs_grep(pattern, glob or "*")
    return hits, fs_tools.format_grep(hits)


def _t_fs_diff(path: str, new_content: str) -> tuple[str, str]:
    diff = fs_tools.fs_diff(path, new_content)
    return diff, diff or f"{path}: изменений нет."


def _t_fs_write(path: str, content: str, dry_run: bool = False) -> tuple[dict, str]:
    res = fs_tools.fs_write(path, content, dry_run)
    return res, _format_write(res)


def _format_write(res: dict) -> str:
    """Отчёт о записи в том виде, в каком его увидят и модель, и человек."""
    if not res["changed"]:
        return f"{res['path']}: изменений нет, файл не тронут."
    if res["dry_run"]:
        head = (f"{res['path']}: предпросмотр (dry_run), на диск НЕ записано. "
                f"{'Файл будет создан.' if res['created'] else 'Файл будет изменён.'}")
    else:
        head = f"{res['path']}: {'создан' if res['created'] else 'изменён'}."
    return f"{head}\n\n{res['diff']}"


# Реестр: имя → функция, описание для модели, схема аргументов.
# Функции возвращают (raw, text): raw — объекты для кода офлайн-планов,
# text — компактное представление для LLM и для лога.
TOOLS: dict[str, dict] = {
    "fs_list": {
        "fn": _t_fs_list,
        "description": "Список файлов проекта (рекурсивно). С него удобно "
                       "начинать, чтобы понять структуру.",
        "args": {"subdir": "подпапка, по умолчанию весь проект (необязательно)"},
    },
    "fs_read": {
        "fn": _t_fs_read,
        "description": "Прочитать файл проекта целиком.",
        "args": {"path": "путь от корня проекта, например api_client.py"},
    },
    "fs_grep": {
        "fn": _t_fs_grep,
        "description": "Поиск по файлам регулярным выражением (регистронезависимо). "
                       "Быстрый способ найти, где что определено и кто это зовёт.",
        "args": {"pattern": "regex, например ApiClient|api_client",
                 "glob": "фильтр файлов, например *.py (необязательно)"},
    },
    "fs_diff": {
        "fn": _t_fs_diff,
        "description": "Показать unified diff между содержимым файла на диске "
                       "и предлагаемым — без записи.",
        "args": {"path": "путь от корня проекта",
                 "new_content": "предлагаемое содержимое целиком"},
    },
    "fs_write": {
        "fn": _t_fs_write,
        "description": "Записать файл (создать новый или заменить целиком). "
                       "Возвращает diff изменений.",
        "args": {"path": "путь от корня проекта",
                 "content": "новое содержимое файла целиком",
                 "dry_run": "true — только показать diff, не записывать "
                            "(необязательно)"},
    },
}


def _tools_help() -> str:
    """Описание инструментов для системного промпта."""
    out = []
    for name, spec in TOOLS.items():
        args = "; ".join(f"{k} — {v}" for k, v in spec["args"].items()) or "без аргументов"
        out.append(f"- {name}({', '.join(spec['args'])})\n"
                   f"  {spec['description']}\n  Аргументы: {args}")
    return "\n".join(out)


SYSTEM_PROMPT = f"""Ты — ассистент, работающий с файлами проекта yuko-sdk.

Тебе ставят ЦЕЛЬ, а не последовательность команд. Какие файлы смотреть, что
искать и что править — решаешь ты сам, с помощью инструментов ниже.

ИНСТРУМЕНТЫ:
{_tools_help()}

ПРАВИЛА РАБОТЫ:
1. Сначала разберись в фактах (fs_list / fs_grep / fs_read), только потом правь.
2. Никогда не выдумывай содержимое файлов — сначала прочитай их.
3. Перед записью убедись, что новое содержимое согласовано с реальным кодом.
4. Не повторяй один и тот же вызов с теми же аргументами.
5. Закончив, дай итог по существу: что нашёл, что изменил, какие выводы.

ФОРМАТ ОТВЕТА — СТРОГО один JSON-объект и НИЧЕГО больше. Никакого текста
до или после, никаких markdown-блоков, никаких пояснений.

Чтобы вызвать инструмент:
{{"thought": "почему я это делаю", "action": "fs_grep", "action_input": {{"pattern": "ApiClient", "glob": "*.py"}}}}

Чтобы закончить работу:
{{"thought": "фактов достаточно", "final_answer": "итог на русском языке"}}
"""


# ============================================================ разбор ответа ===
def _extract_json(text: str) -> dict | None:
    """Достаёт первый JSON-объект из ответа модели.

    Модели любят обернуть JSON в ```json … ``` или добавить «Вот мой ответ:».
    Поэтому: сначала честный json.loads, потом срезаем заборы, потом ищем
    первый сбалансированный {...} посимвольно (с учётом строк и экранирования).
    """
    if not text:
        return None

    raw = text.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # ```json … ``` → содержимое забора
    if "```" in raw:
        parts = raw.split("```")
        for part in parts[1:]:
            body = part[4:] if part.lower().startswith("json") else part
            found = _first_object(body)
            if found is not None:
                return found

    return _first_object(raw)


def _first_object(text: str) -> dict | None:
    """Первый сбалансированный {...} в тексте, разобранный как JSON."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break  # этот кандидат битый — пробуем следующую {
        start = text.find("{", start + 1)
    return None


# ============================================================== ast-разбор ====
def _fmt_args(node: ast.FunctionDef, skip_self: bool = False) -> str:
    """Сигнатура аргументов функции текстом — из ast, не из регулярок."""
    a = node.args
    parts: list[str] = []

    positional = list(a.posonlyargs) + list(a.args)
    # Дефолты прижаты к концу позиционных аргументов.
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)

    for arg, default in zip(positional, defaults):
        if skip_self and arg.arg in ("self", "cls"):
            continue
        piece = arg.arg
        if default is not None:
            piece += f"={ast.unparse(default)}"
        parts.append(piece)
        if a.posonlyargs and arg is a.posonlyargs[-1]:
            parts.append("/")

    if a.vararg:
        parts.append(f"*{a.vararg.arg}")
    elif a.kwonlyargs:
        parts.append("*")

    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        piece = arg.arg
        if default is not None:
            piece += f"={ast.unparse(default)}"
        parts.append(piece)

    if a.kwarg:
        parts.append(f"**{a.kwarg.arg}")

    return ", ".join(parts)


def _fn_info(node: ast.FunctionDef, skip_self: bool = False) -> dict:
    """Единая карточка функции/метода: имя, сигнатура, docstring, публичность."""
    decorators = {ast.unparse(d) for d in node.decorator_list}
    return {
        "name": node.name,
        "args": _fmt_args(node, skip_self=skip_self),
        "full_args": _fmt_args(node),
        "doc": ast.get_docstring(node),
        "public": not node.name.startswith("_"),
        "lineno": node.lineno,
        "is_property": "property" in decorators,
        "required": _required_args(node),
    }


def _required_args(node: ast.FunctionDef) -> list[str]:
    """Обязательные позиционные аргументы (без self и без дефолтов)."""
    a = node.args
    positional = list(a.posonlyargs) + list(a.args)
    n_required = len(positional) - len(a.defaults)
    return [arg.arg for arg in positional[:n_required]
            if arg.arg not in ("self", "cls")]


def analyze_source(source: str, path: str) -> dict:
    """Разбирает Python-модуль в структуру: докстринг, константы, функции, классы.

    Единственный разборщик кода в проекте — им пользуются и генерация доки,
    и генерация README, и проверка инвариантов.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return {"path": path, "error": f"синтаксическая ошибка: {e}",
                "doc": None, "constants": [], "functions": [], "classes": []}

    info = {"path": path, "error": None, "doc": ast.get_docstring(tree),
            "constants": [], "functions": [], "classes": []}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["functions"].append(_fn_info(node))

        elif isinstance(node, ast.ClassDef):
            cls = {"name": node.name, "doc": ast.get_docstring(node),
                   "lineno": node.lineno, "methods": [], "properties": []}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m = _fn_info(sub, skip_self=True)
                    (cls["properties"] if m["is_property"] else cls["methods"]).append(m)
            info["classes"].append(cls)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    info["constants"].append((target.id, ast.unparse(node.value)))

    return info


def _iter_public_defs(info: dict):
    """Все публичные функции и методы модуля как (полное_имя, карточка)."""
    for fn in info["functions"]:
        if fn["public"]:
            yield fn["name"], fn
    for cls in info["classes"]:
        for m in cls["methods"] + cls["properties"]:
            if m["public"]:
                yield f"{cls['name']}.{m['name']}", m


def _is_snake_case(name: str) -> bool:
    """Имя модуля в snake_case: строчные, цифры, подчёркивания."""
    return all(ch.islower() or ch.isdigit() or ch == "_" for ch in name) \
        and not name.startswith("_")


# ====================================================== генерация артефактов ==
def render_api_doc(info: dict) -> str:
    """Собирает docs/api.md строго по разобранному коду api_client.py.

    Ничего не выдумывает: всё — из ast. Поэтому дока не может «разъехаться»
    с кодом, а повторный запуск даёт тот же байт-в-байт результат.
    """
    cls = info["classes"][0] if info["classes"] else None
    if not cls:
        return "# API-справочник\n\nВ модуле не найдено ни одного класса.\n"

    mod = info["path"].removesuffix(".py")
    out = [f"# API-справочник: {cls['name']}", ""]

    if cls["doc"]:
        out += [cls["doc"].strip().splitlines()[0], ""]
    out += [f"Класс `{cls['name']}` из модуля `{mod}` — основная точка входа "
            f"в yuko-sdk.", "",
            "> Файл сгенерирован автоматически из кода `" + info["path"] + "` "
            "(agent.py, сценарий «обновление доки»). Правьте код — "
            "перегенерируйте документ.", ""]

    # --- быстрый старт: собран из реальной сигнатуры __init__ и первого метода
    init = next((m for m in cls["methods"] if m["name"] == "__init__"), None)
    first = next((m for m in cls["methods"] if m["public"]), None)
    if init:
        sample = ", ".join(f'{a}="…"' for a in init["required"])
        out += ["## Быстрый старт", "", "```python",
                f"from {mod} import {cls['name']}", "",
                f"client = {cls['name']}({sample})"]
        if first:
            call = ", ".join(f'{a}="…"' for a in first["required"])
            out += [f"data = client.{first['name']}({call})"]
        out += ["```", ""]

    if info["constants"]:
        out += ["## Константы модуля", ""]
        out += [f"- `{name} = {value}`" for name, value in info["constants"]]
        out += [""]

    # --- публичные методы
    out += [f"## Публичные методы `{cls['name']}`", ""]
    if init:
        out += _render_member(cls["name"], init, "конструктор")
    for m in cls["methods"]:
        if m["public"]:
            out += _render_member(cls["name"], m, "метод")

    # --- свойства
    if any(p["public"] for p in cls["properties"]):
        out += ["## Свойства", ""]
        for p in cls["properties"]:
            if p["public"]:
                doc = (p["doc"] or "Описание отсутствует.").strip()
                out += [f"### `{p['name']}`", "", "Только чтение (`@property`).",
                        "", doc, ""]

    # --- приватное: перечисляем, но не документируем
    private = [m for m in cls["methods"] if not m["public"]
               and not m["name"].startswith("__")]
    if private:
        out += ["## Внутренние методы", "",
                "Не предназначены для вызова из клиентского кода:", ""]
        out += [f"- `{m['name']}(self, {m['args']})`" for m in private]
        out += [""]

    return "\n".join(out).rstrip() + "\n"


_DOC_SECTIONS = ("Аргументы:", "Возвращает:", "Исключения:", "Args:", "Returns:")


def _doc_to_md(doc: str) -> list[str]:
    """Docstring в стиле CONVENTIONS.md → markdown.

    «Аргументы:» с отступом в четыре пробела — это в markdown блок кода,
    а не список. Переводим такие секции в честные списки: заголовок жирным,
    строки `имя: описание` — пунктами.
    """
    lines = [l.rstrip() for l in (doc or "").strip().splitlines()]
    out: list[str] = []
    in_section = False

    for line in lines:
        stripped = line.strip()

        if stripped in _DOC_SECTIONS:
            in_section = True
            if out and out[-1]:
                out.append("")
            out += [f"**{stripped}**", ""]
            continue

        if not stripped:
            in_section = False
            out.append("")
            continue

        if in_section and line.startswith((" ", "\t")):
            # «name: описание» → пункт списка; описание без имени → просто пункт.
            if ":" in stripped and not stripped.split(":", 1)[0].strip().count(" "):
                name, desc = stripped.split(":", 1)
                out.append(f"- `{name.strip()}` — {desc.strip()}")
            else:
                out.append(f"- {stripped}")
            continue

        in_section = False
        out.append(stripped)

    # схлопываем хвостовые пустые строки
    while out and not out[-1]:
        out.pop()
    return out


def _render_member(cls_name: str, m: dict, kind: str) -> list[str]:
    """Секция markdown по одному методу: заголовок, docstring или пометка."""
    out = [f"### `{m['name']}(self, {m['args']})`" if m["args"]
           else f"### `{m['name']}(self)`", ""]
    if m["doc"]:
        out += _doc_to_md(m["doc"]) + [""]
    else:
        out += [f"_Docstring отсутствует в коде — нарушение CONVENTIONS.md "
                f"(`{cls_name}.{m['name']}`)._", ""]
    return out


def render_readme(modules: list[dict], files: list[str]) -> str:
    """Собирает README.md проекта из ast-разбора всех модулей.

    Сам README из списка файлов исключён намеренно: иначе первый прогон
    и второй давали бы разный результат, и run.sh перестал бы быть идемпотентным.
    """
    out = ["# yuko-sdk", "",
           "Учебная библиотека для работы с API таможенного брокера Юко: "
           "нотификации ФСБ, декларации, отчёты.", "",
           "> Файл сгенерирован автоматически ассистентом (`agent.py`, "
           "сценарий «генерация README») по коду проекта.", "",
           "## Возможности", ""]

    for mod in modules:
        first_line = (mod["doc"] or "").strip().splitlines()
        summary = first_line[0] if first_line else "описание отсутствует"
        out.append(f"- **`{mod['path']}`** — {summary}")
    out.append("")

    # --- структура
    out += ["## Структура", "", "```"]
    out += [f for f in files if f != "README.md"]
    out += ["```", ""]

    # --- публичный API
    out += ["## Публичный API", ""]
    for mod in modules:
        out += [f"### `{mod['path']}`", ""]
        if mod["constants"]:
            out += ["Константы: "
                    + ", ".join(f"`{n} = {v}`" for n, v in mod["constants"]), ""]

        for cls in mod["classes"]:
            doc = (cls["doc"] or "").strip().splitlines()
            out.append(f"- `class {cls['name']}` — "
                       f"{doc[0] if doc else 'описание отсутствует'}")
            for m in cls["methods"]:
                if m["public"] or m["name"] == "__init__":
                    d = (m["doc"] or "").strip().splitlines()
                    tail = f" — {d[0]}" if d else ""
                    out.append(f"  - `{m['name']}({m['args']})`{tail}")
            for p in cls["properties"]:
                if p["public"]:
                    d = (p["doc"] or "").strip().splitlines()
                    tail = f" — {d[0]}" if d else ""
                    out.append(f"  - `{p['name']}` *(property)*{tail}")

        for fn in mod["functions"]:
            if fn["public"]:
                d = (fn["doc"] or "").strip().splitlines()
                tail = f" — {d[0]}" if d else ""
                out.append(f"- `{fn['name']}({fn['args']})`{tail}")
        out.append("")

    out += ["## Установка", "",
            "Внешних зависимостей нет — нужен только Python 3.10+.", "",
            "```bash", "git clone <repo>", "cd yuko-sdk", "```", "",
            "## Использование", "", "```python",
            "from handlers import make_default_client, handle_notification", "",
            'client = make_default_client(token="secret")',
            'status = handle_notification(client, decl_id="42")', "```", "",
            "## Соглашения", "",
            "Правила кода — в [CONVENTIONS.md](CONVENTIONS.md). "
            "Документация — в [docs/](docs/).", ""]

    return "\n".join(out).rstrip() + "\n"


# =========================================================== офлайн-планы =====
# Сценарий = набор весов ключевых слов. Побеждает наибольшая сумма.
_SCENARIO_KEYWORDS = {
    "find_usage": {"использ": 3, "места": 2, "вызыв": 2, "кто зовёт": 3,
                   "usage": 3, "где": 1, "apiclient": 1, "найди": 1},
    "update_docs": {"api.md": 3, "документац": 2, "доку": 2, "справочник": 2,
                    "приведи": 1, "обнови": 1, "соответствие": 1, "актуализ": 2},
    "gen_readme": {"readme": 3, "сгенерируй": 1, "генерац": 1, "создай файл": 2},
    "check_conventions": {"conventions": 3, "инвариант": 3, "правил": 2,
                          "соглашен": 2, "провер": 1, "нарушен": 2, "lint": 2},
}


def detect_scenario(goal: str) -> str | None:
    """Определяет сценарий по ключевым словам цели. None — плана нет."""
    blob = (goal or "").lower()
    scores = {name: sum(w for kw, w in kws.items() if kw in blob)
              for name, kws in _SCENARIO_KEYWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else None


def offline_plan(goal: str) -> list[dict]:
    """Детерминированный план шагов для цели — когда LLM недоступна.

    Шаг — это один из трёх видов:
      * вызов инструмента: {"thought", "action", "action_input"}, где
        action_input — либо готовый dict, либо callable(raw) -> dict
        (аргументы, вычисленные из результатов предыдущих шагов);
      * динамическое ветвление: {"thought", "expand": callable(raw) -> [шаги]}
        — когда число шагов заранее неизвестно (например, «прочитать все .py»);
      * финал: {"thought", "final_answer": str | callable(raw) -> str}.

    `raw` — список сырых результатов уже выполненных шагов (объекты, не текст).
    """
    scenario = detect_scenario(goal)
    if scenario == "find_usage":
        return _plan_find_usage()
    if scenario == "update_docs":
        return _plan_update_docs()
    if scenario == "gen_readme":
        return _plan_gen_readme()
    if scenario == "check_conventions":
        return _plan_check_conventions()
    return _plan_fallback(goal)


# --- сценарий 1: поиск использования API -------------------------------------
def _plan_find_usage() -> list[dict]:
    """Где определён ApiClient, кто его импортирует и кто вызывает."""
    return [
        {"thought": "Ищу все упоминания ApiClient и модуля api_client в коде.",
         "action": "fs_grep",
         "action_input": {"pattern": r"ApiClient|api_client", "glob": "*.py"}},
        {"thought": "Группирую совпадения по файлам и классифицирую роли.",
         "final_answer": lambda raw: _report_usage(raw[0])},
    ]


def _classify_hit(text: str) -> str:
    """Роль строки: определение / импорт / создание клиента / вызов метода."""
    t = text.strip()
    if t.startswith("class ApiClient"):
        return "определение"
    if t.startswith(("import ", "from ")):
        return "импорт"
    if "ApiClient(" in t:
        return "создание экземпляра"
    return "упоминание"


def _report_usage(hits: list[dict]) -> str:
    """Отчёт по использованию ApiClient: file:line + роли + сводка."""
    if not hits:
        return "ApiClient в проекте не используется."

    by_file: dict[str, list[dict]] = {}
    for h in hits:
        by_file.setdefault(h["file"], []).append(h)

    out = [f"Найдено {len(hits)} упоминаний в {len(by_file)} файлах.", ""]

    defined, importers, creators = [], [], []
    for path, file_hits in by_file.items():
        out.append(f"**{path}**")
        for h in file_hits:
            role = _classify_hit(h["text"])
            out.append(f"  {path}:{h['line']}: {h['text'].strip()}   → {role}")
            if role == "определение":
                defined.append(f"{path}:{h['line']}")
            elif role == "импорт":
                importers.append(path)
            elif role == "создание экземпляра":
                creators.append(f"{path}:{h['line']}")
        out.append("")

    out += ["## Сводка", "",
            "- **Где определён:** " + (", ".join(defined) or "не найдено"),
            "- **Кто импортирует:** "
            + (", ".join(sorted(set(importers))) or "никто"),
            "- **Кто создаёт экземпляр:** " + (", ".join(creators) or "никто"),
            "",
            "Транспорт изолирован в `api_client.py`: остальные модули ходят "
            "в API только через `ApiClient`, поэтому смена протокола "
            "затрагивает один файл."]
    return "\n".join(out)


# --- сценарий 2: обновление доки по коду -------------------------------------
def _plan_update_docs() -> list[dict]:
    """Читаем код и старую доку, генерируем новую строго по ast."""
    return [
        {"thought": "Читаю код api_client.py — он источник правды для доки.",
         "action": "fs_read", "action_input": {"path": "api_client.py"}},
        {"thought": "Читаю текущую docs/api.md, чтобы понять расхождения.",
         "action": "fs_read", "action_input": {"path": "docs/api.md"}},
        {"thought": "Разбираю код через ast и переписываю доку под реальный API.",
         "action": "fs_write",
         "action_input": lambda raw: {
             "path": "docs/api.md",
             "content": render_api_doc(analyze_source(raw[0], "api_client.py"))}},
        {"thought": "Сверяю, что именно разошлось, и подвожу итог.",
         "final_answer": lambda raw: _report_docs(raw[0], raw[1], raw[2])},
    ]


def _report_docs(code: str, old_doc: str, write_res: dict) -> str:
    """Итог по обновлению доки: что разошлось, что стало."""
    info = analyze_source(code, "api_client.py")
    cls = info["classes"][0] if info["classes"] else None
    if not cls:
        return "В api_client.py не найдено класса — обновлять нечего."

    real = {m["name"] for m in cls["methods"]} | {p["name"] for p in cls["properties"]}
    documented = {name for name in real if f"`{name}(" in old_doc
                  or f"### `{name}`" in old_doc}

    # Что дока обещала, а кода нет: ищем заголовки старой доки вида `## `name(`.
    ghosts = []
    for line in old_doc.splitlines():
        s = line.strip()
        if s.startswith("## `") and "(" in s:
            name = s[4:].split("(")[0].strip()
            if name not in real:
                ghosts.append(name)

    missing = sorted(n for n in real
                     if n not in documented and not n.startswith("_"))

    out = ["Дока `docs/api.md` пересобрана из кода `api_client.py` через `ast`.",
           "", "## Расхождения старой доки с кодом", ""]
    if ghosts:
        out.append("- **Описаны несуществующие методы:** "
                   + ", ".join(f"`{g}()`" for g in ghosts)
                   + " — в коде их нет.")
    if missing:
        out.append("- **Не описаны реальные члены класса:** "
                   + ", ".join(f"`{m}`" for m in missing) + ".")

    init = next((m for m in cls["methods"] if m["name"] == "__init__"), None)
    if init and "retries" in old_doc and "retries" not in init["args"]:
        out.append(f"- **Неверная сигнатура конструктора:** дока обещает "
                   f"`retries=3`, в коде `__init__(self, {init['args']})`. "
                   f"Повторы живут в `retry_count`, а не в параметре.")

    no_doc = [f"`{cls['name']}.{m['name']}`" for m in cls["methods"]
              if m["public"] and not m["doc"]]
    if no_doc:
        out.append("- **Нет docstring в коде:** " + ", ".join(no_doc)
                   + " — в доке помечены явно, чинить надо в коде.")
    if len(out) == 3:
        out.append("- Расхождений не найдено.")

    out += ["", "## Результат", ""]
    if not write_res["changed"]:
        out.append("Дока уже соответствует коду — файл не тронут.")
    elif write_res["dry_run"]:
        out.append("Режим `--dry-run`: на диск ничего не записано, "
                   "выше показан предполагаемый diff.")
    else:
        out.append("Файл `docs/api.md` обновлён.")
    return "\n".join(out)


# --- сценарий 3: генерация README --------------------------------------------
def _plan_gen_readme() -> list[dict]:
    """Смотрим структуру, читаем все .py, собираем README из ast."""
    return [
        {"thought": "Смотрю структуру проекта, чтобы понять из чего он состоит.",
         "action": "fs_list", "action_input": {"subdir": "."}},
        {"thought": "Читаю каждый Python-модуль — README собираю по коду, "
                    "а не по догадкам.",
         "expand": lambda raw: [
             {"thought": f"Читаю {path}.",
              "action": "fs_read", "action_input": {"path": path}}
             for path in raw[0] if path.endswith(".py")]},
        {"thought": "Разбираю модули через ast и собираю README.md.",
         "action": "fs_write",
         "action_input": lambda raw: {
             "path": "README.md",
             # raw[0] — список файлов, raw[1:] — исходники прочитанных модулей
             # (ровно в том же порядке, в каком их подставил expand-шаг).
             "content": render_readme(
                 [analyze_source(src, path)
                  for path, src in zip([p for p in raw[0] if p.endswith(".py")],
                                       raw[1:])],
                 raw[0])}},
        {"thought": "Подвожу итог по сгенерированному README.",
         "final_answer": lambda raw: _report_readme(raw[0], raw[-1])},
    ]


def _report_readme(files: list[str], write_res: dict) -> str:
    """Итог по генерации README."""
    py = [f for f in files if f.endswith(".py")]
    out = [f"README.md собран по коду проекта: разобрано {len(py)} "
           f"Python-модулей ({', '.join(py)}) из {len(files)} файлов.", ""]
    if not write_res["changed"]:
        out.append("Содержимое совпало с существующим README.md — "
                   "файл не тронут (генерация идемпотентна).")
    elif write_res["dry_run"]:
        out.append("Режим `--dry-run`: файл не записан, показан только diff.")
    else:
        out.append(f"Файл `README.md` "
                   f"{'создан' if write_res['created'] else 'обновлён'}: "
                   f"описание, структура, публичный API, установка.")
    return "\n".join(out)


# --- сценарий 4: проверка инвариантов ----------------------------------------
def _plan_check_conventions() -> list[dict]:
    """Читаем правила, собираем модули, ищем нарушения через ast и grep."""
    return [
        {"thought": "Читаю CONVENTIONS.md — какие правила вообще проверять.",
         "action": "fs_read", "action_input": {"path": "CONVENTIONS.md"}},
        {"thought": "Собираю список Python-модулей проекта.",
         "action": "fs_list", "action_input": {"subdir": "."}},
        {"thought": "Ищу print() в библиотечном коде — правило запрещает его.",
         "action": "fs_grep",
         "action_input": {"pattern": r"(?<![\w.])print\s*\(", "glob": "*.py"}},
        {"thought": "Читаю каждый модуль для ast-обхода на предмет docstring.",
         "expand": lambda raw: [
             {"thought": f"Читаю {path}.",
              "action": "fs_read", "action_input": {"path": path}}
             for path in raw[1] if path.endswith(".py")]},
        {"thought": "Свожу нарушения в отчёт.",
         "final_answer": lambda raw: _report_conventions(raw[1], raw[2], raw[3:])},
    ]


def _report_conventions(files: list[str], print_hits: list[dict],
                        sources: list[str]) -> str:
    """Отчёт о нарушениях CONVENTIONS.md: docstring, print(), snake_case."""
    py = [f for f in files if f.endswith(".py")]
    violations: list[str] = []

    # Правило 1: у каждой публичной функции и метода обязан быть docstring.
    no_doc: list[str] = []
    for path, src in zip(py, sources):
        info = analyze_source(src, path)
        if info["error"]:
            violations.append(f"{path}: {info['error']}")
            continue
        for name, m in _iter_public_defs(info):
            if not m["doc"]:
                no_doc.append(f"{path}:{m['lineno']}: `{name}({m['args']})` — "
                              f"нет docstring")

    # Правило 2: print() в библиотечном коде запрещён.
    prints = [f"{h['file']}:{h['line']}: {h['text'].strip()}" for h in print_hits]

    # Правило 3: имена модулей — snake_case.
    bad_names = [f"{p}: имя модуля не в snake_case"
                 for p in py
                 if not _is_snake_case(p.rsplit("/", 1)[-1].removesuffix(".py"))]

    out = ["# Проверка соответствия CONVENTIONS.md", "",
           f"Проверено модулей: {len(py)} ({', '.join(py)}).", ""]

    out += ["## Документирование — публичные функции без docstring", ""]
    out += ([f"- {v}" for v in no_doc] if no_doc
            else ["- Нарушений нет."])
    out += [""]

    out += ["## Библиотечный код — `print()`", ""]
    out += ([f"- {v}" for v in prints] if prints
            else ["- Нарушений нет: `print()` в библиотечном коде отсутствует."])
    out += [""]

    out += ["## Именование — модули в snake_case", ""]
    out += ([f"- {v}" for v in bad_names] if bad_names
            else ["- Нарушений нет."])
    out += [""]

    total = len(no_doc) + len(prints) + len(bad_names) + len(violations)
    if violations:
        out += ["## Прочее", ""] + [f"- {v}" for v in violations] + [""]

    out += ["---", "",
            f"**Итого нарушений: {total}.**"]
    if no_doc:
        out += ["", "Что чинить: добавить docstring на русском (первая строка — "
                    "краткое описание, далее «Аргументы:» и «Возвращает:») "
                    "к перечисленным членам. Приватные (`_request`) "
                    "правило не затрагивает."]
    return "\n".join(out)


# --- запасной план -----------------------------------------------------------
def _plan_fallback(goal: str) -> list[dict]:
    """Цель не распознана: показываем структуру и честно об этом говорим."""
    return [
        {"thought": "Цель не подходит ни под один готовый офлайн-план — "
                    "смотрю хотя бы структуру проекта.",
         "action": "fs_list", "action_input": {"subdir": "."}},
        {"thought": "Объясняю, что могу сделать без LLM.",
         "final_answer": lambda raw: (
             f"Для цели «{goal}» готового офлайн-плана нет, а LLM недоступна "
             f"(нет DEEPSEEK_API_KEY и не поднята Ollama).\n\n"
             f"Структура проекта ({len(raw[0])} файлов):\n"
             + "\n".join(f"- {f}" for f in raw[0])
             + "\n\nБез LLM доступны 4 сценария:\n"
               "1. «найди все места где используется ApiClient»\n"
               "2. «приведи docs/api.md в соответствие с кодом api_client.py»\n"
               "3. «сгенерируй README.md для проекта»\n"
               "4. «проверь соответствие кода правилам из CONVENTIONS.md»\n\n"
               "Либо задайте DEEPSEEK_API_KEY / поднимите Ollama — "
               "тогда план построит модель.")},
    ]


# ================================================================== агент =====
class FileAgent:
    """ReAct-агент над файлами проекта.

    Получает цель, сам выбирает инструменты, сам решает когда остановиться.
    dry_run — защита уровня агента: `fs_write` физически не может записать
    на диск, что бы ни попросила модель.
    """

    def __init__(self, dry_run: bool = False, max_steps: int = 12,
                 verbose: bool = True):
        self.dry_run = dry_run
        self.max_steps = max_steps
        self.verbose = verbose
        self.backend = llm.llm_available()

    # ------------------------------------------------------------ служебное --
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _call_tool(self, name: str, args: dict) -> tuple[object, str]:
        """Выполняет инструмент из реестра. Возвращает (raw, text_for_model)."""
        spec = TOOLS.get(name)
        if not spec:
            known = ", ".join(TOOLS)
            raise ValueError(f"неизвестный инструмент «{name}». Доступны: {known}")

        args = dict(args or {})
        if name == "fs_write" and self.dry_run:
            # Защита, а не опция модели: в dry_run запись невозможна.
            args["dry_run"] = True
        try:
            return spec["fn"](**args)
        except TypeError as e:
            raise ValueError(f"{name}: неверные аргументы ({e})") from e

    @staticmethod
    def _truncate(text: str) -> str:
        """Обрезает observation, чтобы длинный файл не съел весь контекст."""
        if len(text) <= OBS_LIMIT:
            return text
        return (text[:OBS_LIMIT]
                + f"\n… [обрезано, всего {len(text)} символов]")

    def _echo_step(self, n: int, thought: str, action: str, args: dict) -> None:
        shown = {k: (v if not isinstance(v, str) or len(v) <= 60
                     else v[:60] + "…") for k, v in (args or {}).items()}
        self._log(f"\n[шаг {n}] {thought}")
        self._log(f"         → {action}({json.dumps(shown, ensure_ascii=False)})")

    def _echo_obs(self, text: str, full: bool = False) -> None:
        """Краткое эхо observation. Для fs_write — целиком: diff это и есть суть."""
        if full:
            self._log("         ← " + text.replace("\n", "\n           "))
            return
        head = " ".join(text.split())[:OBS_ECHO]
        tail = "…" if len(text) > OBS_ECHO else ""
        self._log(f"         ← {head}{tail}")

    def _record(self, steps: list, writes: list, n: int, thought: str,
                action: str, args: dict, raw: object, obs: str) -> None:
        """Кладёт шаг в протокол; записи fs_write — отдельно, ради отчёта."""
        steps.append({"n": n, "thought": thought, "action": action,
                      "action_input": args, "observation": obs})
        if action == "fs_write" and isinstance(raw, dict):
            writes.append(raw)

    # ----------------------------------------------------------------- run ---
    def run(self, goal: str) -> dict:
        """Главный вход: цель → {"goal","steps","final_answer","writes","backend"}."""
        if not (goal or "").strip():
            raise ValueError("Пустая цель — нечего делать")

        self._log(f"Цель: {goal}")
        self._log(f"Бэкенд: {self.backend}"
                  + ("  |  режим dry-run: запись на диск запрещена"
                     if self.dry_run else ""))

        if self.backend == "offline":
            return self._run_offline(goal)

        result = self._run_llm(goal)
        if result is None:
            # LLM была «доступна», но замолчала (сеть отвалилась в процессе).
            # Конкретный шаг и имя плана уже записаны в лог из _run_llm.
            self.backend = "offline"
            return self._run_offline(goal)
        return result

    # ------------------------------------------------------------ LLM-режим --
    def _run_llm(self, goal: str) -> dict | None:
        """ReAct-цикл с моделью. None — модель не ответила ни разу."""
        history = [{"role": "system", "content": SYSTEM_PROMPT},
                   {"role": "user", "content": f"ЦЕЛЬ: {goal}"}]
        steps: list[dict] = []
        writes: list[dict] = []

        for n in range(1, self.max_steps + 1):
            reply = llm.chat(history)
            if reply is None:
                # Сеть отвалилась — на любом шаге, не только на первом.
                # Если для цели есть детерминированный план — доводим цель
                # до конца офлайном (None = сигнал run() переключить режим).
                # Плана нет — честно останавливаемся, не притворяясь.
                scenario = detect_scenario(goal)
                if scenario is None and n > 1:
                    return self._finish(
                        goal, steps, writes,
                        f"LLM перестала отвечать на шаге {n}, а готового "
                        f"офлайн-плана для этой цели нет — работа прервана. "
                        f"Выполненные шаги см. в протоколе.")
                self._log(f"\n[LLM отвалилась на шаге {n} → перехожу "
                          f"на офлайн-план "
                          f"{f'«{scenario}»' if scenario else '(общий)'}]")
                return None

            move = _extract_json(reply)
            if move is None:
                history += [{"role": "assistant", "content": reply},
                            {"role": "user",
                             "content": "Ответ не разобран. Верни СТРОГО один "
                                        "JSON-объект и ничего кроме него."}]
                continue

            history.append({"role": "assistant",
                            "content": json.dumps(move, ensure_ascii=False)})
            thought = str(move.get("thought", "")).strip()

            if "final_answer" in move:
                self._log(f"\n[шаг {n}] {thought}\n         → финальный ответ")
                return self._finish(goal, steps, writes,
                                    str(move["final_answer"]))

            action = move.get("action")
            args = move.get("action_input") or {}
            if not action:
                history.append({"role": "user",
                                "content": "Нужно поле action или final_answer."})
                continue

            # Модели регулярно шлют action_input строкой с JSON внутри
            # («"action_input": "{\"path\": \"utils.py\"}"») — разбираем.
            if isinstance(args, str):
                args = _extract_json(args) or {}
            if not isinstance(args, dict):
                history.append({"role": "user",
                                "content": "action_input должен быть JSON-объектом "
                                           "с аргументами инструмента. Повтори шаг."})
                continue

            self._echo_step(n, thought, action, args)
            try:
                raw, text = self._call_tool(action, args)
                obs = self._truncate(text)
            except Exception as e:
                raw, obs = None, f"ОШИБКА: {e}"

            self._echo_obs(obs, full=(action == "fs_write"))
            self._record(steps, writes, n, thought, action, args, raw, obs)
            history.append({"role": "user", "content": f"OBSERVATION:\n{obs}"})

        return self._finish(goal, steps, writes,
                            f"Лимит в {self.max_steps} шагов исчерпан, "
                            f"итог не сформулирован. Увеличьте --max-steps.")

    # --------------------------------------------------------- офлайн-режим --
    def _run_offline(self, goal: str) -> dict:
        """Исполняет детерминированный план: те же инструменты, зашитый порядок."""
        scenario = detect_scenario(goal)
        self._log(f"LLM недоступна → офлайн-план"
                  + (f" «{scenario}»" if scenario else " (общий)"))

        queue = list(offline_plan(goal))
        raw_results: list = []
        steps: list[dict] = []
        writes: list[dict] = []
        n = 0

        while queue and n < self.max_steps:
            step = queue.pop(0)
            thought = step.get("thought", "")

            # Ветвление: число шагов зависит от уже полученных данных.
            if "expand" in step:
                queue = list(step["expand"](raw_results)) + queue
                continue

            if "final_answer" in step:
                fa = step["final_answer"]
                self._log(f"\n[шаг {n + 1}] {thought}\n         → финальный ответ")
                answer = fa(raw_results) if callable(fa) else str(fa)
                return self._finish(goal, steps, writes, answer)

            n += 1
            action = step["action"]
            args = step["action_input"]
            if callable(args):
                args = args(raw_results)
            if action == "fs_write" and self.dry_run:
                args = {**args, "dry_run": True}

            self._echo_step(n, thought, action, args)
            try:
                raw, text = self._call_tool(action, args)
                obs = self._truncate(text)
            except Exception as e:
                raw, obs = None, f"ОШИБКА: {e}"

            self._echo_obs(obs, full=(action == "fs_write"))
            raw_results.append(raw)
            self._record(steps, writes, n, thought, action, args, raw, obs)

        return self._finish(goal, steps, writes,
                            "Офлайн-план не дошёл до финала: "
                            f"лимит {self.max_steps} шагов исчерпан.")

    # -------------------------------------------------------------- финал ----
    def _finish(self, goal: str, steps: list, writes: list,
                answer: str) -> dict:
        self._log("\n" + "=" * 72)
        self._log(answer)
        return {"goal": goal, "steps": steps, "final_answer": answer,
                "writes": writes, "backend": self.backend}


if __name__ == "__main__":
    FileAgent().run("найди все места где используется ApiClient")
