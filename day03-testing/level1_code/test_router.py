"""Unit-тесты Router Pattern — task35/router.py.

Роутер решает маршрут запроса ТН ВЭД: быстрый CODE_LOOKUP если в тексте
есть готовый 10-значный код, иначе полный FULL_PIPELINE; callback-кнопки
уходят в специализированные агенты.
"""
import router


# ---------- extract_code ----------

def test_code_with_spaces():
    assert router.extract_code("код 8525 89 300 0 пожалуйста") == "8525893000"


def test_code_with_spaces_variant():
    assert router.extract_code("товар 8517 62 00 09") == "8517620009"


def test_no_code():
    assert router.extract_code("камеры видеонаблюдения без кода") is None


def test_too_short_is_not_code():
    assert router.extract_code("артикул 12345") is None


def test_too_many_digits_rejected():
    # 16 цифр — не 10-значный код ТН ВЭД
    assert router.extract_code("ean 1234567890123456") is None


# ---------- route_request ----------

def test_route_spaced_code_is_lookup():
    route, code = router.route_request("код 8525 89 300 0")
    assert route == "CODE_LOOKUP"
    assert code == "8525893000"


def test_route_plain_text_is_full_pipeline():
    route, code = router.route_request("как классифицировать дрон с камерой")
    assert route == "FULL_PIPELINE"
    assert code is None


def test_route_callback_alt():
    assert router.route_request("любой текст", callback_data="alt:8525") == ("ALT_CODES_AGENT", None)


def test_route_callback_psn():
    assert router.route_request("любой текст", callback_data="psn:8525") == ("EEC_EXPLAIN_AGENT", None)


def test_callback_priority_over_code():
    # Callback важнее содержимого сообщения
    route, code = router.route_request("код 8525 89 300 0", callback_data="alt:x")
    assert route == "ALT_CODES_AGENT"
    assert code is None
