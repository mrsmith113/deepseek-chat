"""Обработчики бизнес-сценариев: нотификации и декларации."""

from api_client import ApiClient


def handle_notification(client, decl_id):
    """Забирает статус нотификации ФСБ по идентификатору декларации.

    Аргументы:
        client: экземпляр ApiClient.
        decl_id: идентификатор декларации.

    Возвращает:
        dict со статусом нотификации.
    """
    response = client.get("/notifications", params={"decl_id": decl_id})
    return {"decl_id": decl_id, "raw": response}


def handle_declaration(client, data):
    """Отправляет декларацию на регистрацию.

    Аргументы:
        client: экземпляр ApiClient.
        data: словарь с полями декларации.

    Возвращает:
        dict с результатом регистрации.
    """
    response = client.post("/declarations", payload=data)
    return {"registered": response.get("status") == 200, "raw": response}


def make_default_client(token):
    """Собирает клиент с настройками по умолчанию."""
    return ApiClient("https://api.notifikat.ru", token)
