"""
Query Rewriter — расширяет поисковый запрос через Qwen3.

Стратегия: LLM добавляет синонимы и смежные термины из области ВЭД,
что улучшает recall при векторном поиске.
"""

import json
import urllib.request


OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:14b"

SYSTEM_PROMPT = (
    "Ты помощник для улучшения поиска по базе знаний о ВЭД и таможне России. /no_think\n"
    "Получаешь поисковый запрос и возвращаешь расширенную версию: "
    "оригинал + синонимы + официальные термины + смежные понятия через пробел.\n"
    "Возвращай ТОЛЬКО расширенную строку. Никаких объяснений, никаких заголовков."
)

FEW_SHOT = [
    ("Нотификация ФСБ",
     "Нотификация ФСБ шифровальные средства криптография СКЗИ ввоз оборудования ФСБ России реестр нотификаций разрешение на ввоз"),
    ("Как оформить декларацию?",
     "Как оформить декларацию? таможенная декларация ДТ подача документов таможенное оформление ГТД участник ВЭД"),
    ("Как перевести деньги в Китай?",
     "Как перевести деньги в Китай? платежи иностранным поставщикам валютный контроль SWIFT CNY юань трансграничные переводы"),
]


def _http_post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def rewrite_query(question: str) -> str:
    """Вернуть расширенный поисковый запрос."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_q, assistant_a in FEW_SHOT:
        messages.append({"role": "user", "content": user_q})
        messages.append({"role": "assistant", "content": assistant_a})
    messages.append({"role": "user", "content": question})

    result = _http_post(
        f"{OLLAMA_URL}/api/chat",
        {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 150},
        },
    )
    rewritten = result.get("message", {}).get("content", "").strip()
    return rewritten if rewritten else question


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Как перевести деньги в Китай?"
    print(f"Оригинал:  {q}")
    print(f"Расширено: {rewrite_query(q)}")
