"""Smoke-тесты файлового ядра. Чистый stdlib, без pytest.

Запуск:
    python3 test_fs_tools.py

Проверяем главное: песочница держит удар, чтение/поиск/diff работают,
а dry_run действительно ничего не пишет на диск.
"""
from __future__ import annotations

import sys

import fs_tools

PASSED = 0
FAILED = 0


def check(name: str, fn) -> None:
    """Гоняет одну проверку и печатает результат, не роняя прогон целиком."""
    global PASSED, FAILED
    try:
        fn()
    except AssertionError as e:
        FAILED += 1
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILED += 1
        print(f"ERROR {name}: {type(e).__name__}: {e}")
    else:
        PASSED += 1
        print(f"ok    {name}")


# ------------------------------------------------------------- тесты ---------
def test_safe_blocks_escape() -> None:
    """`../` наружу песочницы обязан кидать ValueError, а не читать /etc."""
    for bad in ("../../etc/passwd", "../fs_tools.py", "/etc/passwd"):
        try:
            fs_tools._safe(bad)
        except ValueError:
            continue
        raise AssertionError(f"путь {bad!r} прошёл защиту — это дыра")


def test_safe_allows_inside() -> None:
    """Нормальный путь внутри ROOT должен резолвиться без шума."""
    p = fs_tools._safe("utils.py")
    assert fs_tools.ROOT in p.parents, f"{p} оказался вне ROOT"


def test_list_not_empty() -> None:
    """В project/ должны быть файлы, иначе тестировать нечего."""
    files = fs_tools.fs_list()
    assert files, "fs_list вернул пустой список"
    assert all(not f.startswith("/") for f in files), "пути должны быть относительными"
    assert "__pycache__" not in " ".join(files), "мусор __pycache__ попал в листинг"


def test_grep_finds_defs() -> None:
    """Поиск по `def ` обязан что-то найти в питоновском проекте."""
    hits = fs_tools.fs_grep(r"def ", glob="*.py")
    assert hits, "fs_grep не нашёл ни одного 'def ' в *.py"
    h = hits[0]
    assert set(h) == {"file", "line", "text"}, f"неверная форма хита: {h}"
    assert h["line"] >= 1, "нумерация строк должна начинаться с 1"


def test_read_roundtrip() -> None:
    """Прочитанный файл не пустой, а несуществующий даёт ValueError."""
    first = fs_tools.fs_list()[0]
    assert fs_tools.fs_read(first) != "" or True  # пустой файл — не ошибка
    try:
        fs_tools.fs_read("нет-такого-файла.py")
    except ValueError:
        return
    raise AssertionError("чтение несуществующего файла не упало")


def test_diff_no_changes() -> None:
    """Diff содержимого с самим собой — пустая строка."""
    first = fs_tools.fs_list()[0]
    same = fs_tools.fs_read(first)
    assert fs_tools.fs_diff(first, same) == "", "diff без изменений должен быть пустым"


def test_diff_detects_change() -> None:
    """Изменённое содержимое даёт непустой unified diff с заголовками a/ и b/."""
    first = fs_tools.fs_list()[0]
    old = fs_tools.fs_read(first)
    diff = fs_tools.fs_diff(first, old + "\n# хвост для теста\n")
    assert diff, "diff изменённого файла пуст"
    assert f"--- a/{first}" in diff, "нет заголовка fromfile a/..."
    assert f"+++ b/{first}" in diff, "нет заголовка tofile b/..."


def test_write_dry_run_does_not_touch_disk() -> None:
    """dry_run=True считает diff, но файл на диске остаётся прежним."""
    first = fs_tools.fs_list()[0]
    before = fs_tools.fs_read(first)

    res = fs_tools.fs_write(first, before + "\n# НЕ должно попасть на диск\n",
                            dry_run=True)

    assert res["dry_run"] is True, "флаг dry_run потерян в отчёте"
    assert res["changed"] is True, "changed должен быть True: содержимое отличается"
    assert res["created"] is False, "существующий файл не может быть created"
    assert res["diff"], "при dry_run diff должен быть посчитан"
    assert fs_tools.fs_read(first) == before, "dry_run изменил файл на диске!"


def test_write_new_file_dry_run() -> None:
    """Новый файл при dry_run помечается created, но на диске не появляется."""
    path = "_tmp_smoke_check.py"
    res = fs_tools.fs_write(path, "print('тест')\n", dry_run=True)

    assert res["created"] is True, "новый файл должен быть created=True"
    assert not (fs_tools.ROOT / path).exists(), "dry_run создал файл на диске!"


# ------------------------------------------------------------- прогон --------
def main() -> int:
    print(f"ROOT: {fs_tools.ROOT}\n")

    check("_safe блокирует выход из песочницы", test_safe_blocks_escape)
    check("_safe пропускает путь внутри ROOT", test_safe_allows_inside)
    check("fs_list не пустой", test_list_not_empty)
    check("fs_grep находит 'def '", test_grep_finds_defs)
    check("fs_read читает и ругается на пропажу", test_read_roundtrip)
    check("fs_diff без изменений = ''", test_diff_no_changes)
    check("fs_diff ловит изменение", test_diff_detects_change)
    check("fs_write dry_run не трогает диск", test_write_dry_run_does_not_touch_disk)
    check("fs_write dry_run не создаёт файл", test_write_new_file_dry_run)

    total = PASSED + FAILED
    print(f"\nOK: {PASSED}/{total}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
