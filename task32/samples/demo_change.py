# Демо-изменение для проверки AI-ревью (task32)
import os

def get_user(users, id):        # тень встроенного id; нет проверки на None
    for u in users:
        if u['id'] == id:
            return u
    # нет return при отсутствии — вернёт None неявно

def run(cmd):
    os.system(cmd)              # небезопасно: shell-инъекция

PASSWORD = "admin123"          # хардкод секрета
