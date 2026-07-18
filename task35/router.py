"""
router.py — Router Pattern для оркестратора ТН ВЭД.
Концепция курса БЛМ: Router — агент выбирает маршрут на основе типа запроса.

Маршруты:
  FULL_PIPELINE    — полный fan-out на 4 агента (стандартный путь)
  CODE_LOOKUP      — в запросе уже есть 10-значный код → пропускаем RAG, быстрее + дешевле
  ALT_CODES_AGENT  — callback кнопки «Альтернативные коды»
  EEC_EXPLAIN_AGENT — callback кнопки «Пояснения ЕЭК»
"""
import re
import logging

log = logging.getLogger(__name__)

# Паттерн: 10-цифровой код ТН ВЭД (с пробелами или без)
# Примеры: 8525893000, 8525 89 300 0, 8517 62 00 09
_CODE_RE = re.compile(r'\b\d[\d\s]{9,12}\d\b')


def extract_code(msg: str) -> str | None:
    """Ищет 10-значный код ТН ВЭД в сообщении. Возвращает цифры без пробелов или None."""
    m = _CODE_RE.search(msg)
    if m:
        digits = re.sub(r'\D', '', m.group())
        if len(digits) == 10:
            return digits
    return None


def route_request(user_msg: str, callback_data: str | None = None) -> tuple[str, str | None]:
    """
    Определяет маршрут обработки запроса.

    Возвращает (route_name, extracted_code_or_None).

    Router Pattern:
      1. Callback кнопок → специализированные агенты
      2. Запрос содержит 10-значный код → CODE_LOOKUP (быстрый путь)
      3. Иначе → FULL_PIPELINE (fan-out на 4 агента)
    """
    if callback_data:
        if callback_data.startswith("alt:"):
            return "ALT_CODES_AGENT", None
        if callback_data.startswith("psn:"):
            return "EEC_EXPLAIN_AGENT", None

    code = extract_code(user_msg)
    if code:
        log.info(f"[Router] CODE_LOOKUP → {code}")
        return "CODE_LOOKUP", code

    log.info("[Router] FULL_PIPELINE")
    return "FULL_PIPELINE", None
