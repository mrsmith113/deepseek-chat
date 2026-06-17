import os
import requests
import time
import threading

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")

PROMPT = (
    "Объясни концепцию 'энтропии' — сначала научно точно, "
    "затем придумай яркую creative метафору из жизни."
)

MODELS = {
    "1": {
        "name":    "🟢 V4 Flash  (слабая/быстрая)",
        "id":      "deepseek-v4-flash",
        "input":   0.14,   # $ за 1M токенов
        "output":  0.28,
    },
    "2": {
        "name":    "🟡 V4 Pro    (средняя)",
        "id":      "deepseek-v4-pro",
        "input":   0.435,
        "output":  0.87,
    },
    "3": {
        "name":    "🔴 Reasoner  (сильная/думающая)",
        "id":      "deepseek-reasoner",
        "input":   0.55,
        "output":  2.19,
    },
}

ANALYST_SYSTEM = (
    "Тебе дали одинаковый запрос, выполненный тремя разными моделями DeepSeek. "
    "Сравни ответы по: точности, глубине, креативности. "
    "Для каждой модели сформулируй: для каких задач она лучше подходит. "
    "Будь конкретным и практичным. Говори кратко."
)

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def calc_cost(input_tokens, output_tokens, model):
    cost = (input_tokens / 1_000_000 * model["input"] +
            output_tokens / 1_000_000 * model["output"])
    return cost

def ask_deepseek(model_id, prompt):
    result = {}
    done_event = threading.Event()

    def do_request():
        messages = [{"role": "user", "content": prompt}]
        t0 = time.time()
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "messages": messages},
        )
        elapsed = time.time() - t0
        data = response.json()
        result["answer"]  = data["choices"][0]["message"]["content"]
        result["elapsed"] = elapsed
        result["usage"]   = data.get("usage", {})
        done_event.set()

    thread = threading.Thread(target=do_request)
    thread.start()
    if not done_event.wait(timeout=3):
        print("Ну и задачка, всё ещё думаю :)")
    thread.join()
    return result

def print_stats(result, model):
    usage = result["usage"]
    input_tok  = usage.get("prompt_tokens", 0)
    output_tok = usage.get("completion_tokens", 0)
    total_tok  = usage.get("total_tokens", 0)
    cost       = calc_cost(input_tok, output_tok, model)

    print(f"\n📊 Статистика:")
    print(f"   ⏱  Время ответа : {result['elapsed']:.2f} сек")
    print(f"   📥 Input токены : {input_tok}")
    print(f"   📤 Output токены: {output_tok}")
    print(f"   📦 Всего токенов: {total_tok}")
    print(f"   💰 Стоимость    : ${cost:.6f}")

def pick(available, allow_analyst=False):
    print("\nВыбери:")
    for k in available:
        print(f"  [{k}] {MODELS[k]['name']}")
    if allow_analyst:
        print("  [А] 📈 Аналитик — сравнить ответы (доступен после первого)")
    print("  [В] Выход")

    valid = list(available) + (["А"] if allow_analyst else []) + ["В"]
    while True:
        choice = input("Твой выбор: ").strip().upper()
        if choice in valid:
            return choice
        print(f"Введи одно из: {', '.join(valid)}")

# ───────────────────────────────────────────
# Старт
# ───────────────────────────────────────────
divider("ЗАДАНИЕ 5 — Сравнение моделей")
print(f"\nЗапрос:\n  {PROMPT}\n")
print("Три модели — один запрос. Сравниваем качество, скорость и стоимость.")

available = ["1", "2", "3"]
done = {}      # key -> result
answers = {}   # key -> текст ответа

while True:
    choice = pick(available, allow_analyst=len(done) > 0)

    if choice == "В":
        print("\nВыход. Пока!\n")
        break

    elif choice == "А":
        divider("📈 АНАЛИТИК — сравнение моделей")
        parts = "\n\n".join(
            f"{MODELS[k]['name']}:\n{answers[k]}" for k in sorted(done.keys())
        )
        analyst_prompt = f"Запрос:\n{PROMPT}\n\nОтветы моделей:\n{parts}"
        print("Думаю...\n")
        res = ask_deepseek("deepseek-v4-flash", analyst_prompt)
        print(res["answer"])

        if available:
            print("\nЕщё остались модели. Продолжаем?")
        else:
            print("\nВсе модели опрошены.")
            break

    else:
        m = MODELS[choice]
        available.remove(choice)
        divider(m["name"])
        print(f"Модель: {m['id']}")
        print("Думаю...\n")

        result = ask_deepseek(m["id"], PROMPT)
        done[choice] = result
        answers[choice] = result["answer"]

        print(result["answer"])
        print_stats(result, m)

        # Все три опрошены — финальный аналитик
        if not available:
            divider("📈 АНАЛИТИК — финальное сравнение всех трёх моделей")
            print("Все модели опрошены. Аналитик подводит итог...\n")

            # Сводная таблица
            print("┌─────────────────────────────┬──────────┬────────┬────────────┬────────────┐")
            print("│ Модель                      │ Время    │ Токены │ Стоимость  │            │")
            print("├─────────────────────────────┼──────────┼────────┼────────────┼────────────┤")
            for k in ["1", "2", "3"]:
                r = done[k]
                u = r["usage"]
                cost = calc_cost(
                    u.get("prompt_tokens", 0),
                    u.get("completion_tokens", 0),
                    MODELS[k]
                )
                name = MODELS[k]["name"][:28].ljust(28)
                print(f"│ {name}│ {r['elapsed']:6.2f}s  │ {u.get('total_tokens',0):6} │ ${cost:.6f} │            │")
            print("└─────────────────────────────┴──────────┴────────┴────────────┴────────────┘")

            parts = "\n\n".join(
                f"{MODELS[k]['name']}:\n{answers[k]}" for k in ["1", "2", "3"]
            )
            analyst_prompt = (
                f"Запрос:\n{PROMPT}\n\n"
                f"Ответы моделей:\n{parts}\n\n"
                f"Также учти статистику:\n" +
                "\n".join(
                    f"{MODELS[k]['name']}: время {done[k]['elapsed']:.2f}с, "
                    f"токены {done[k]['usage'].get('total_tokens',0)}, "
                    f"стоимость ${calc_cost(done[k]['usage'].get('prompt_tokens',0), done[k]['usage'].get('completion_tokens',0), MODELS[k]):.6f}"
                    for k in ["1","2","3"]
                )
            )
            res = ask_deepseek("deepseek-v4-flash", analyst_prompt)
            print("\n" + res["answer"])

            divider("КОНЕЦ")
            print("  Ссылки:")
            print("  https://api-docs.deepseek.com")
            print("  https://github.com/mrsmith113/deepseek-chat\n")
            break
