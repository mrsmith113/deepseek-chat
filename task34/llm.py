"""LLM-каскад: DeepSeek → Ollama → офлайн.

Одна ответственность: превратить список сообщений в текст ответа модели —
или честно вернуть None, если ни один бэкенд недоступен.

Каскад намеренно «тихий»: нет ключа, нет сети, не поднята Ollama, таймаут,
кривой JSON в ответе — всё это не исключение, а None. Вызывающий код
(agent.offline_plan) обязан уметь работать без модели, поэтому падать здесь
не на чем: отсутствие LLM — штатный режим, а не авария.

Переменные окружения:
    DEEPSEEK_API_KEY  — ключ DeepSeek. Нет ключа → бэкенд пропускается.
    DEEPSEEK_MODEL    — модель DeepSeek (по умолчанию deepseek-chat).
    OLLAMA_HOST       — адрес Ollama (по умолчанию http://localhost:11434).
    OLLAMA_MODEL      — модель Ollama (по умолчанию qwen3:14b).
"""
from __future__ import annotations

import json
import os
import urllib.request

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_TIMEOUT = 90
OLLAMA_TIMEOUT = 120
# Окно контекста Ollama. Дефолт модели (~4k) меньше истории ReAct-цикла,
# и переполнение обрезается молча — поэтому задаём явно.
OLLAMA_NUM_CTX = 32768

# Плейсхолдеры из примеров конфигов — ключом не считаются.
_FAKE_KEYS = {"", "YOUR_DEEPSEEK_API_KEY", "sk-xxx", "changeme"}


def _ollama_url(path: str) -> str:
    """Полный URL к Ollama с учётом OLLAMA_HOST."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    return f"{host}{path}"


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict | None:
    """POST JSON → разобранный JSON-ответ. Любая ошибка → None, без исключений."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        # Сеть/ключ/таймаут/кривой JSON — всё это «бэкенда нет», а не сбой.
        return None


# ------------------------------------------------------------- бэкенды -------
def _deepseek(messages: list[dict], temperature: float) -> str | None:
    """Генерация через DeepSeek API. Нет ключа или сети → None."""
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if key.strip() in _FAKE_KEYS:
        return None

    data = _post_json(
        DEEPSEEK_URL,
        {"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
         "messages": messages,
         "temperature": temperature},
        {"Authorization": f"Bearer {key}"},
        DEEPSEEK_TIMEOUT)
    if not data:
        return None
    try:
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except (KeyError, IndexError, TypeError):
        return None


def _ollama(messages: list[dict], temperature: float) -> str | None:
    """Генерация через локальную Ollama (/api/chat). Не поднята → None."""
    data = _post_json(
        _ollama_url("/api/chat"),
        {"model": os.getenv("OLLAMA_MODEL", "qwen3:14b"),
         "messages": messages,
         "stream": False,
         # num_ctx обязателен: дефолт у qwen3:14b ~4k токенов, а история
         # ReAct-цикла (до 12 шагов × OBS_LIMIT=4000 символов observation) даёт
         # 15-20k. Без явного окна Ollama тихо обрежет контекст с начала —
         # модель потеряет системный промпт и план, не сообщив об этом.
         "options": {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX}},
        {},
        OLLAMA_TIMEOUT)
    if not data:
        return None
    try:
        return (data["message"]["content"] or "").strip() or None
    except (KeyError, TypeError):
        return None


# ------------------------------------------------------------- публичное -----
def chat(messages: list[dict], temperature: float = 0.2) -> str | None:
    """Ответ модели на список сообщений [{"role","content"}, ...].

    Порядок: DeepSeek → Ollama → None. None означает «модели нет,
    переходи в офлайн-режим», а не ошибку.
    """
    if not messages:
        return None
    return _deepseek(messages, temperature) or _ollama(messages, temperature)


def llm_available() -> str:
    """Какой бэкенд ответит на chat(): "deepseek" / "ollama" / "offline".

    Проверка дешёвая и настоящая: DeepSeek — по наличию ключа (ходить в платное
    API ради пробы незачем), Ollama — коротким GET /api/tags.
    """
    if os.getenv("DEEPSEEK_API_KEY", "").strip() not in _FAKE_KEYS:
        return "deepseek"
    try:
        with urllib.request.urlopen(_ollama_url("/api/tags"), timeout=2) as r:
            if r.status == 200:
                return "ollama"
    except Exception:
        pass
    return "offline"


if __name__ == "__main__":
    print(f"Активный бэкенд: {llm_available()}")
    reply = chat([{"role": "user", "content": "Ответь одним словом: работает?"}])
    print(f"Ответ: {reply if reply else '(нет LLM — офлайн-режим)'}")
