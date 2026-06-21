import os
import requests
import threading

# Цены DeepSeek ($ за 1M токенов)
PRICE = {
    "input":        0.27,   # cache miss (новые токены)
    "cached":       0.07,   # cache hit (из кэша, дешевле)
    "output":       1.10,
}


def call_api(messages, temperature=0.7, max_tokens=None):
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "your_api_key_here":
        return {"answer": None, "usage": {}, "error": {"message": "API ключ не задан"}}

    result     = {}
    done_event = threading.Event()

    def do():
        body = {
            "model":       "deepseek-chat",
            "messages":    messages,
            "temperature": temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens

        try:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=body,
                timeout=60,
            )
            d = r.json()
            if "choices" in d:
                result["answer"] = d["choices"][0]["message"]["content"]
                result["usage"]  = d.get("usage", {})
                result["error"]  = None
            else:
                result["answer"] = None
                result["usage"]  = {}
                result["error"]  = d.get("error", {"message": str(d)})
        except Exception as e:
            result["answer"] = None
            result["usage"]  = {}
            result["error"]  = {"message": str(e)}
        done_event.set()

    t = threading.Thread(target=do)
    t.start()
    if not done_event.wait(timeout=4):
        print("  Ну и задачка, всё ещё думаю :)")
    t.join()
    return result


def calc_cost(usage):
    """Считаем стоимость с учётом кэша"""
    cached  = usage.get("prompt_cache_hit_tokens", 0)
    miss    = usage.get("prompt_cache_miss_tokens",
                        usage.get("prompt_tokens", 0) - cached)
    output  = usage.get("completion_tokens", 0)

    cost = (miss    / 1_000_000 * PRICE["input"] +
            cached  / 1_000_000 * PRICE["cached"] +
            output  / 1_000_000 * PRICE["output"])
    return cost, cached, miss, output


def format_token_line(usage, agent_name):
    cost, cached, miss, output = calc_cost(usage)
    total = cached + miss + output
    return (
        f"  📊 [{agent_name}] "
        f"вход: {miss+cached} (кэш: {cached} | новые: {miss}) | "
        f"выход: {output} | итого: {total} | ${cost:.6f}"
    )
