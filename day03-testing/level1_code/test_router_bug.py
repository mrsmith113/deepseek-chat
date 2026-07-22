"""Регрессия-сторож: тест ВСКРЫЛ реальный дефект router.extract_code.

СИМПТОМ: голый 10-значный код без пробелов ("8525893000") НЕ распознаётся,
запрос уходит в дорогой FULL_PIPELINE вместо быстрого CODE_LOOKUP.

ROOT CAUSE (task35/router.py:19):
    _CODE_RE = re.compile(r'...\\b\\d[\\d\\s]{9,12}\\d\\b...')
    Средний класс {9,12} + якорные \\d по краям = минимум 1+9+1 = 11 символов.
    Строка "8525893000" — 10 символов → под паттерн не подходит.
    При этом docstring функции приводит "8525893000" как валидный пример.

ФИКС (одна цифра): {9,12} → {8,12}  (минимум 1+8+1 = 10 символов).
    9-значные строки всё равно отсекаются проверкой len(digits)==10.

Тест помечен xfail(strict=True): пока баг жив — xfail (сюит зелёный).
Как только router.py починят — тест начнёт проходить и strict=True
превратит неожиданный PASS в XPASS→fail, заставив снять маркер.
"""
import pytest
import router


@pytest.mark.bug
@pytest.mark.xfail(strict=True, reason="router.py:19 regex {9,12} требует >=11 символов; фикс -> {8,12}")
def test_bare_10digit_code_should_be_recognised():
    # Ожидаемое ПРАВИЛЬНОЕ поведение (сейчас падает — баг):
    assert router.extract_code("8525893000") == "8525893000"


@pytest.mark.bug
def test_bare_code_current_behaviour_documented():
    # Фиксируем фактическое (дефектное) поведение, чтобы фикс был заметен в diff.
    assert router.extract_code("8525893000") is None
    assert router.route_request("8525893000") == ("FULL_PIPELINE", None)
