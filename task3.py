import os
import requests
import threading

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")

TASK = (
    "У Анны есть 3 коробки: в одной яблоки, в другой апельсины, "
    "в третьей и то и другое. Все коробки подписаны НЕПРАВИЛЬНО. "
    "Анна достаёт один фрукт из коробки с надписью «Яблоки» и видит апельсин. "
    "Как узнать содержимое всех коробок?"
)

EXPERTS = {
    "1": {
        "name": "🔍 Логик",
        "desc": "анализирует условия и строит цепочку выводов",
        "system": "Ты — Логик. Анализируй условия задачи строго и последовательно, строй цепочку логических выводов.",
    },
    "2": {
        "name": "🛠 Инженер",
        "desc": "ищет алгоритм, проверяет все варианты перебором",
        "system": "Ты — Инженер. Реши задачу алгоритмически: перебери все возможные варианты и найди единственно верный.",
    },
    "3": {
        "name": "🎲 Интуит",
        "desc": "ищет короткий путь, объясняет просто и наглядно",
        "system": "Ты — Интуит. Найди самое простое и наглядное объяснение решения, без лишних формальностей.",
    },
}

CRITIC_SYSTEM = (
    "Ты — 🎯 Критик. Тебе дали задачу и ответы экспертов. "
    "Найди ошибки в их рассуждениях, выдели лучшее из каждого ответа "
    "и дай окончательный правильный вывод."
)

FINAL_CRITIC_SYSTEM = (
    "Ты — 🎯 Критик. Тебе дали задачу и ответы всех экспертов. "
    "Подведи итог: какой из экспертов справился лучше всего? "
    "Расставь оценки каждому эксперту по шкале от 1 до 5 с обоснованием."
)

def divider(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def ask_deepseek(system, user):
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
            json={"model": "deepseek-chat", "messages": messages},
        )
        result["answer"] = response.json()["choices"][0]["message"]["content"]
        done_event.set()

    thread = threading.Thread(target=do_request)
    thread.start()

    # Ждём 3 секунды, если не пришло — пишем сообщение
    if not done_event.wait(timeout=3):
        print("Ну и задачка, всё ещё думаю :)")

    thread.join()
    return result["answer"]

def pick_from(options_dict, extra=None, prompt="Твой выбор"):
    """options_dict: {key: label}, extra: {key: label} доп. варианты"""
    all_opts = {**options_dict}
    if extra:
        all_opts.update(extra)
    while True:
        choice = input(f"{prompt}: ").strip().upper()
        if choice in all_opts:
            return choice
        print(f"Введи одно из: {', '.join(all_opts.keys())}")

# ───────────────────────────────────────────
# ШАГ 1: постановка задачи + прямой ответ
# ───────────────────────────────────────────
divider("ЗАДАЧА")
print(TASK)

divider("ШАГ 1 — Прямой ответ (без инструкций)")
print("Отправляем задачу в API и ждём ответ...\n")
direct = ask_deepseek(None, TASK)
print(direct)

# ───────────────────────────────────────────
# Знакомство с экспертами
# ───────────────────────────────────────────
divider("ЭКСПЕРТЫ")
print("У нас есть три эксперта и Критик:\n")
for key, e in EXPERTS.items():
    print(f"  [{key}] {e['name']} — {e['desc']}")
print("\n  [К] 🎯 Критик — оценивает ответы экспертов и даёт финальный вердикт")
print("       (доступен после хотя бы одного эксперта)\n")

# ───────────────────────────────────────────
# Основной цикл опроса экспертов
# ───────────────────────────────────────────
available = ["1", "2", "3"]
done = []       # опрошенные эксперты (по порядку)
answers = {}    # ответы экспертов

step = 1
critic_used = False

while available or not critic_used:

    # Формируем варианты выбора
    opts = {k: EXPERTS[k]["name"] for k in available}
    extra = {}
    if done:  # критик доступен после хотя бы одного эксперта
        extra["К"] = "🎯 Критик"

    # Если эксперты кончились — сразу к критику
    if not available:
        break

    # Приглашение
    print(f"\nКого хотим услышать {'первым' if step == 1 else 'следующим'}?")
    for k in available:
        print(f"  [{k}] {EXPERTS[k]['name']} — {EXPERTS[k]['desc']}")
    if done:
        print("  [К] 🎯 Критик — может высказаться уже сейчас")

    choice = pick_from(opts, extra if done else None)

    if choice == "К":
        # Промежуточный критик
        divider("🎯 КРИТИК — промежуточная оценка")
        expert_answers = "\n\n".join(
            f"{EXPERTS[k]['name']}:\n{answers[k]}" for k in done
        )
        critic_prompt = f"Задача:\n{TASK}\n\nОтветы экспертов:\n{expert_answers}"
        print("Думаю...\n")
        print(ask_deepseek(CRITIC_SYSTEM, critic_prompt))
        critic_used = True

    else:
        # Опрашиваем эксперта
        available.remove(choice)
        done.append(choice)
        e = EXPERTS[choice]
        divider(f"ЭКСПЕРТ: {e['name']}")
        print("Думаю...\n")
        answers[choice] = ask_deepseek(e["system"], TASK)
        print(answers[choice])
        step += 1

        # Если это был последний эксперт — выходим из цикла
        if not available:
            break

# ───────────────────────────────────────────
# Финальный критик с оценками
# ───────────────────────────────────────────
divider("🎯 ФИНАЛ — Критик подводит итог")
print("Все эксперты высказались. Критик расставит оценки по шкале 1–5...\n")

expert_answers = "\n\n".join(
    f"{EXPERTS[k]['name']}:\n{answers[k]}" for k in done
)
final_prompt = f"Задача:\n{TASK}\n\nОтветы всех экспертов:\n{expert_answers}"
print(ask_deepseek(FINAL_CRITIC_SYSTEM, final_prompt))

divider("КОНЕЦ")
print("  Спасибо за участие!\n")
