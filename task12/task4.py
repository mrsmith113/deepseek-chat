import os
import requests
import threading

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")

PROMPT = (
    "Объясни концепцию 'энтропии' — сначала научно точно, "
    "затем придумай яркую creative метафору из жизни."
)

TEMPS = {
    "1": {"temp": 0.0,  "label": "🧊 temperature = 0.0  (точность, детерминизм)"},
    "2": {"temp": 0.7,  "label": "⚖️  temperature = 0.7  (баланс)"},
    "3": {"temp": 1.2,  "label": "🔥 temperature = 1.2  (креативность, разнообразие)"},
}

CRITIC_SYSTEM = (
    "Тебе дали одинаковый запрос, выполненный с разной температурой (temperature). "
    "Сравни ответы по точности, креативности и разнообразию. "
    "Для каждого варианта сформулируй: для каких задач он лучше подходит. "
    "Будь конкретным и практичным."
)

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def ask_deepseek(system, user, temperature=0.7):
    result = {}
    done_event = threading.Event()

    def do_request():
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": temperature,
            },
        )
        result["answer"] = response.json()["choices"][0]["message"]["content"]
        done_event.set()

    thread = threading.Thread(target=do_request)
    thread.start()
    if not done_event.wait(timeout=3):
        print("Ну и задачка, всё ещё думаю :)")
    thread.join()
    return result["answer"]

def pick(available_keys, allow_critic=False, allow_exit=True):
    opts = [k for k in ["1", "2", "3"] if k in available_keys]
    extra = []
    if allow_critic:
        extra.append("К")
    if allow_exit:
        extra.append("В")

    print("\nВыбери:")
    for k in opts:
        print(f"  [{k}] {TEMPS[k]['label']}")
    if allow_critic:
        print("  [К] 🎯 Критик — сравнить ответы и дать рекомендации")
    print("  [В] Выход")

    all_valid = opts + extra
    while True:
        choice = input("Твой выбор: ").strip().upper()
        if choice in all_valid:
            return choice
        print(f"Введи одно из: {', '.join(all_valid)}")

# ───────────────────────────────────────────
# Старт
# ───────────────────────────────────────────
divider("ЗАДАНИЕ 4 — Температура")
print(f"\nЗапрос который будем отправлять:\n\n  {PROMPT}\n")
print("Один и тот же запрос — три разные температуры.")
print("Выбирай порядок сам. Критик доступен после первого ответа.")

available = {"1", "2", "3"}
done = {}  # key -> answer

while True:
    choice = pick(available, allow_critic=len(done) > 0)

    if choice == "В":
        print("\nВыход. Пока!\n")
        break

    elif choice == "К":
        divider("🎯 КРИТИК — анализ и рекомендации")
        parts = "\n\n".join(
            f"{TEMPS[k]['label']}:\n{done[k]}" for k in sorted(done.keys())
        )
        critic_prompt = f"Запрос:\n{PROMPT}\n\nОтветы:\n{parts}"
        print("Думаю...\n")
        print(ask_deepseek(CRITIC_SYSTEM, critic_prompt, temperature=0))

        # После критика — продолжаем если есть ещё варианты
        if available:
            print("\nЕщё остались варианты температуры. Продолжаем?")
        else:
            print("\nВсе варианты опрошены. Выход.")
            break

    else:
        t = TEMPS[choice]
        available.discard(choice)
        done[choice] = None
        divider(t["label"])
        print("Думаю...\n")
        answer = ask_deepseek(None, PROMPT, temperature=t["temp"])
        done[choice] = answer
        print(answer)

        # Все три опрошены — финальный критик автоматически
        if not available:
            divider("🎯 КРИТИК — финальный разбор всех трёх температур")
            print("Все варианты получены. Критик подводит итог...\n")
            parts = "\n\n".join(
                f"{TEMPS[k]['label']}:\n{done[k]}" for k in ["1", "2", "3"]
            )
            critic_prompt = f"Запрос:\n{PROMPT}\n\nОтветы:\n{parts}"
            print(ask_deepseek(CRITIC_SYSTEM, critic_prompt, temperature=0))
            divider("КОНЕЦ")
            print("  Спасибо!\n")
            break
