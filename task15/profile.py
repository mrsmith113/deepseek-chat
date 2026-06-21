from db import save_profile, list_profiles, set_active_profile, delete_profile

PROFILE_FIELDS = {
    "name":         {"label": "Имя",               "default": "Пользователь"},
    "role":         {"label": "Роль / должность",   "default": "не указана"},
    "company":      {"label": "Компания",            "default": "не указана"},
    "level":        {"label": "Уровень экспертизы", "default": "средний",
                     "options": ["новичок", "средний", "эксперт"]},
    "style":        {"label": "Стиль ответов",      "default": "подробный",
                     "options": ["краткий", "подробный", "с примерами"]},
    "format":       {"label": "Формат",             "default": "текст",
                     "options": ["текст", "списки", "таблицы"]},
    "language":     {"label": "Язык",               "default": "русский",
                     "options": ["русский", "английский"]},
    "restrictions": {"label": "Ограничения",        "default": "нет"},
}


def profile_wizard(profile_name=None):
    """Мастер создания профиля"""
    if not profile_name:
        profile_name = input("  Название профиля: ").strip() or "Профиль 1"

    print(f"\n  Настройка профиля '{profile_name}'")
    print("  Нажми Enter чтобы оставить значение по умолчанию.\n")

    data = {}
    for key, meta in PROFILE_FIELDS.items():
        default = meta["default"]
        if "options" in meta:
            opts = "  /  ".join(f"[{i+1}] {o}" for i, o in enumerate(meta["options"]))
            print(f"  {meta['label']}: {opts}")
            print(f"  (Enter = {default}): ", end="")
            ch = input().strip()
            if ch.isdigit() and 1 <= int(ch) <= len(meta["options"]):
                value = meta["options"][int(ch)-1]
            else:
                value = default
        else:
            print(f"  {meta['label']} (Enter = {default}): ", end="")
            value = input().strip() or default
        data[key] = value

    save_profile(profile_name, data, set_active=True)
    print(f"\n  ✅ Профиль '{profile_name}' сохранён и активирован!\n")
    return profile_name, data


def profile_to_system_prompt(profile):
    """Профиль → system prompt блок"""
    style_map = {
        "краткий":     "Отвечай кратко — только суть, без воды.",
        "подробный":   "Отвечай подробно с объяснениями.",
        "с примерами": "Обязательно приводи конкретные примеры.",
    }
    format_map = {
        "текст":   "Используй сплошной текст.",
        "списки":  "Используй маркированные списки.",
        "таблицы": "Где возможно — используй таблицы.",
    }
    level_map = {
        "новичок": "Объясняй просто, избегай сложных терминов.",
        "средний":  "Используй профессиональные термины с кратким пояснением.",
        "эксперт":  "Используй профессиональный язык без упрощений.",
    }
    lang = ("Отвечай на русском языке."
            if profile.get("language") == "русский"
            else "Answer in English.")
    restr = (f"Ограничения: {profile['restrictions']}."
             if profile.get("restrictions", "нет") != "нет" else "")

    return (
        f"👤 Профиль пользователя:\n"
        f"Имя: {profile.get('name','Пользователь')}. "
        f"Роль: {profile.get('role','не указана')}. "
        f"Компания: {profile.get('company','не указана')}.\n"
        f"{level_map.get(profile.get('level','средний'),'')} "
        f"{style_map.get(profile.get('style','подробный'),'')} "
        f"{format_map.get(profile.get('format','текст'),'')} "
        f"{lang} {restr}"
    )


def show_profiles_menu():
    """Показать список профилей"""
    profiles = list_profiles()
    if not profiles:
        return []
    print(f"\n  {'ID':<4} {'Название':<20} {'Активный'}")
    print(f"  {'-'*4} {'-'*20} {'-'*8}")
    for pid, name, data, is_active in profiles:
        mark = "✅" if is_active else ""
        print(f"  {pid:<4} {name:<20} {mark}")
    return profiles


def switch_profile():
    """Переключить активный профиль"""
    profiles = list_profiles()
    if not profiles:
        print("\n  Профилей нет.\n")
        return None, None

    show_profiles_menu()
    valid = {str(p[0]): p for p in profiles}
    print("\n  [N] Новый профиль")
    choice = input("  Выбери ID или [N]: ").strip().upper()

    if choice == "N":
        return profile_wizard()
    elif choice in valid:
        import json
        p = valid[choice]
        set_active_profile(p[1])
        data = json.loads(p[2])
        print(f"\n  ✅ Активирован профиль '{p[1]}'\n")
        return p[1], data
    return None, None
