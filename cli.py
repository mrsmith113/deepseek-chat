import os
import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")

history = []

settings = {
    "mode": "free",  # free | strict | nano
}

HELP = """
Команды:
  /mode free       — без ограничений (по умолчанию)
  /mode strict     — краткий формат + стоп [КОНЕЦ]
  /mode nano       — ровно 10 слов, не больше
  /settings        — показать текущие настройки
  /clear           — очистить историю диалога
  /help            — эта справка
  выход / exit     — выйти
"""

STRICT_SYSTEM = (
    "Отвечай строго в формате: "
    "1) краткое резюме одним предложением, "
    "2) не более 3 пунктов списка. "
    "Максимум 10 слов. "
    "Заверши ответ фразой: [КОНЕЦ]"
)

NANO_SYSTEM = (
    "Отвечай РОВНО в 10 слов — не больше, не меньше. "
    "Только самая суть. Никаких вводных слов и пояснений."
)

def show_settings():
    mode = settings["mode"]
    if mode == "free":
        print("\n⚙️  Режим: FREE (без ограничений)\n")
    elif mode == "strict":
        print("\n⚙️  Режим: STRICT")
        print("   Формат : резюме + до 3 пунктов")
        print("   Длина  : max_tokens = 30")
        print("   Стоп   : [КОНЕЦ]\n")
    elif mode == "nano":
        print("\n⚙️  Режим: NANO")
        print("   Формат : ровно 10 слов")
        print("   Длина  : max_tokens = 30\n")

def build_messages(user_input):
    msgs = []
    if settings["mode"] == "strict":
        msgs.append({"role": "system", "content": STRICT_SYSTEM})
    elif settings["mode"] == "nano":
        msgs.append({"role": "system", "content": NANO_SYSTEM})
    msgs += history
    msgs.append({"role": "user", "content": user_input})
    return msgs

def ask_deepseek(user_input):
    body = {
        "model": "deepseek-chat",
        "messages": build_messages(user_input),
    }
    if settings["mode"] == "strict":
        body["max_tokens"] = 30
        body["stop"] = ["[КОНЕЦ]"]
    elif settings["mode"] == "nano":
        body["max_tokens"] = 30

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    return response.json()["choices"][0]["message"]["content"]

print("=== DeepSeek Chat ===")
print("Введи /help для списка команд\n")

while True:
    user_input = input("Ты: ").strip()

    if not user_input:
        continue

    if user_input.lower() in ("выход", "exit", "quit"):
        print("Пока!")
        break
    elif user_input == "/help":
        print(HELP)
    elif user_input == "/settings":
        show_settings()
    elif user_input == "/clear":
        history.clear()
        print("🗑️  История очищена\n")
    elif user_input == "/mode free":
        settings["mode"] = "free"
        print("✅ Режим: FREE — без ограничений\n")
    elif user_input == "/mode strict":
        settings["mode"] = "strict"
        print("✅ Режим: STRICT — краткий формат, стоп: [КОНЕЦ]\n")
    elif user_input == "/mode nano":
        settings["mode"] = "nano"
        print("✅ Режим: NANO — ровно 10 слов\n")
    else:
        print("DeepSeek: ⏳ думаю...", end="\r")
        answer = ask_deepseek(user_input)
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": answer})
        print(f"DeepSeek: {answer}\n")
