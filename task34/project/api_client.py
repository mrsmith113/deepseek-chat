"""HTTP-клиент для API таможенного брокера Юко.

Модуль предоставляет класс ApiClient — тонкую обёртку над REST API.
Реализация учебная: сетевые вызовы заменены заглушками.
"""

DEFAULT_TIMEOUT = 30
DEFAULT_RETRY_COUNT = 3


class ApiClient:
    """Клиент для работы с API yuko-sdk.

    Хранит базовый URL и токен авторизации, умеет выполнять
    GET- и POST-запросы к путям API.
    """

    def __init__(self, base_url, token, timeout=30):
        """Создаёт клиент.

        Аргументы:
            base_url: базовый адрес API, например "https://api.notifikat.ru".
            token: токен авторизации (Bearer).
            timeout: таймаут запроса в секундах.
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._closed = False
        self._retry_count = DEFAULT_RETRY_COUNT

    @property
    def retry_count(self):
        """Число повторных попыток при сбое запроса."""
        return self._retry_count

    def get(self, path, params=None):
        """Выполняет GET-запрос.

        Аргументы:
            path: путь относительно base_url, например "/declarations/42".
            params: словарь query-параметров.

        Возвращает:
            dict с телом ответа.
        """
        return self._request("GET", path, params or {})

    def post(self, path, payload=None):
        return self._request("POST", path, payload or {})

    def close(self):
        self._closed = True
        return self._closed

    def _request(self, method, path, body):
        """Внутренняя точка выполнения запроса.

        Заглушка: вместо сети возвращает описание запроса.
        """
        if self._closed:
            raise RuntimeError("Клиент уже закрыт")

        return {
            "method": method,
            "url": "{0}{1}".format(self.base_url, path),
            "body": body,
            "timeout": self.timeout,
            "status": 200,
        }
