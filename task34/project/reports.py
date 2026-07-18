"""Построение и выгрузка отчётов по декларациям."""

import csv

import api_client


def build_report(cfg):
    """Строит отчёт по конфигурации.

    Аргументы:
        cfg: словарь с ключами base_url, token, period.

    Возвращает:
        список словарей-строк отчёта.
    """
    client = api_client.ApiClient(cfg["base_url"], cfg["token"])
    response = client.get("/reports", params={"period": cfg.get("period", "month")})
    client.close()

    return [
        {"period": cfg.get("period", "month"), "url": response["url"], "rows": 0},
    ]


def export_csv(rows, path):
    if not rows:
        return 0

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)
