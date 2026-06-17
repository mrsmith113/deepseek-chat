import os
import requests
import threading

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")

ROLES = {
    "1": {
        "name": "👶 Ребёнок (7 лет)",
        "system": (
            "Ты объясняешь всё как будто говоришь с семилетним ребёнком. "
            "Используй простые слова, короткие предложения, смешные и понятные примеры из жизни. "
            "Никаких сложных терминов — только то, что поймёт первоклассник."
        ),
    },
    "2": {
        "name": "🎓 Студент",
        "system": (
            "Ты объясняешь как опытный старшекурсник своему однокурснику. "
            "Используй термины, но объясняй их. Давай примеры из учёбы и практики. "
            "Можно немного неформально, но по делу."
        ),
    },
    "3": {
        "name": "🧑‍🏫 Профессор",
        "system": (
            "Ты объясняешь как профессор с многолетним опытом. "
            "Строгая терминология, глубокий анализ, ссылки на теорию. "
            "Структурированно: определение → суть → примеры → выводы."
        ),
    },
    "4": {
        "name": "🤖 Ассистент (без роли)",
        "system": "Ты полезный ассистент. Отвечай чётко и по делу.",
    },
}


class Agent:
    def __init__(self):
        self.role_key = "4"
        self.history = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.request_count = 0

    @property
    def role(self):
        return ROLES[self.role_key]

    def set_role(self, key):
        self.role_key = key

    def reset(self):
        self.history = []

    def get_history(self):
        return self.history

    def stats(self):
        cost = (self.total_input_tokens / 1_000_000 * 0.14 +
                self.total_output_tokens / 1_000_000 * 0.28)
        return {
            "requests":     self.request_count,
            "input_tokens":  self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens":  self.total_input_tokens + self.total_output_tokens,
            "cost":          cost,
        }

    def run(self, user_input):
        self.history.append({"role": "user", "content": user_input})

        messages = [{"role": "system", "content": self.role["system"]}] + self.history

        result = {}
        done_event = threading.Event()

        def do_request():
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": "deepseek-v4-flash", "messages": messages},
            )
            data = response.json()
            result["answer"] = data["choices"][0]["message"]["content"]
            result["usage"]  = data.get("usage", {})
            done_event.set()

        thread = threading.Thread(target=do_request)
        thread.start()
        if not done_event.wait(timeout=3):
            print("Ну и задачка, всё ещё думаю :)")
        thread.join()

        answer = result["answer"]
        usage  = result.get("usage", {})

        self.history.append({"role": "assistant", "content": answer})
        self.total_input_tokens  += usage.get("prompt_tokens", 0)
        self.total_output_tokens += usage.get("completion_tokens", 0)
        self.request_count       += 1

        return answer


# ───────────────────────────────────────────
# CLI интерфейс
# ───────────────────────────────────────────

def divider(title=""):
    print(f"\n{'='*55}")
    if title:
        print(f"  {title}")
        print(f"{'='*55}")

def show_roles():
    print("\nВыбери роль агента:")
    for k, r in ROLES.items():
        print(f"  [{k}] {r['name']}")

def show_help():
    print("""
Команды:
  /role     — сменить роль агента
  /reset    — сбросить память (начать новый диалог)
  /history  — показать историю диалога
  /stats    — токены и стоимость
  /exit     — выход
""")

agent = Agent()

divider("ЗАДАНИЕ 6 — Агент")
print(f"\nТекущая роль: {agent.role['name']}")
print("Введи /role чтобы выбрать роль, /help для справки.\n")

while True:
    try:
        user_input = input("Ты: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nВыход.")
        break

    if not user_input:
        continue

    elif user_input == "/exit":
        print("\nПока!\n")
        break

    elif user_input == "/help":
        show_help()

    elif user_input == "/role":
        show_roles()
        while True:
            choice = input("Твой выбор [1-4]: ").strip()
            if choice in ROLES:
                agent.set_role(choice)
                print(f"\n✅ Роль изменена: {agent.role['name']}")
                print("   (история сохранена, /reset чтобы сбросить)\n")
                break
            print("Введи 1, 2, 3 или 4")

    elif user_input == "/reset":
        agent.reset()
        print("🗑️  Память сброшена. Начинаем заново.\n")

    elif user_input == "/history":
        history = agent.get_history()
        if not history:
            print("\n  История пуста.\n")
        else:
            divider("ИСТОРИЯ ДИАЛОГА")
            for msg in history:
                role = "Ты" if msg["role"] == "user" else f"Агент ({agent.role['name']})"
                print(f"\n[{role}]\n{msg['content']}")
            print()

    elif user_input == "/stats":
        s = agent.stats()
        divider("СТАТИСТИКА")
        print(f"  Запросов        : {s['requests']}")
        print(f"  Input токены    : {s['input_tokens']}")
        print(f"  Output токены   : {s['output_tokens']}")
        print(f"  Всего токенов   : {s['total_tokens']}")
        print(f"  Стоимость       : ${s['cost']:.6f}")
        print(f"  Текущая роль    : {agent.role['name']}\n")

    else:
        answer = agent.run(user_input)
        print(f"\nАгент ({agent.role['name']}):\n{answer}\n")
