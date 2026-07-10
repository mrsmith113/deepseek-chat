#!/usr/bin/env python3
"""
Task 30 — Тест стабильности LLM-сервиса
Проверяет: сетевой доступ, несколько параллельных запросов, rate limit
"""

import time
import json
import threading
import argparse
import requests
import statistics

_http = requests.Session()
_http.trust_env = False

QUESTIONS = [
    "Что такое нотификация ФСБ?",
    "Как рассчитать таможенную пошлину на ноутбук?",
    "Что такое ТН ВЭД?",
    "Сколько дней идёт груз из Китая морем?",
    "Что такое параллельный импорт?",
]


def single_request(url: str, question: str, idx: int) -> dict:
    t0 = time.time()
    try:
        resp = _http.post(f"{url}/chat", json={
            "messages": [{"role": "user", "content": question}],
            "temperature": 0.3,
            "max_tokens": 512,
        }, timeout=120)
        elapsed = round(time.time() - t0, 2)
        if resp.status_code == 429:
            return {"idx": idx, "status": "rate_limited", "elapsed": elapsed}
        resp.raise_for_status()
        data = resp.json()
        return {
            "idx": idx,
            "status": "ok",
            "elapsed": elapsed,
            "tokens": data.get("tokens", 0),
            "answer_len": len(data.get("message", {}).get("content", "")),
        }
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        return {"idx": idx, "status": "error", "elapsed": elapsed, "error": str(e)}


def test_health(url: str):
    print(f"\n{'='*60}")
    print(f"  Тест 1: Health check → {url}/health")
    print(f"{'='*60}")
    try:
        r = _http.get(f"{url}/health", timeout=5)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"❌ {e}")


def test_info(url: str):
    print(f"\n{'='*60}")
    print(f"  Тест 2: Лимиты контекста → {url}/info")
    print(f"{'='*60}")
    try:
        r = _http.get(f"{url}/info", timeout=5)
        data = r.json()
        print(f"  Модель:        {data['model']}")
        print(f"  Max context:   {data['max_context_tokens']:,} токенов")
        print(f"  Max response:  {data['max_tokens_per_response']:,} токенов")
        print(f"  Rate limit:    {data['rate_limit_rpm']} req/min")
    except Exception as e:
        print(f"❌ {e}")


def test_sequential(url: str):
    print(f"\n{'='*60}")
    print(f"  Тест 3: Последовательные запросы (5 вопросов)")
    print(f"{'='*60}")
    times = []
    for i, q in enumerate(QUESTIONS):
        print(f"  [{i+1}/5] {q[:45]}...", end=" ", flush=True)
        r = single_request(url, q, i)
        times.append(r["elapsed"])
        if r["status"] == "ok":
            print(f"✓ {r['elapsed']}с | {r['tokens']} tok | {r['answer_len']} chars")
        else:
            print(f"✗ {r['status']}: {r.get('error', '')}")

    if times:
        print(f"\n  Среднее время: {statistics.mean(times):.1f}с")
        print(f"  Мин/Макс:      {min(times):.1f}с / {max(times):.1f}с")


def test_parallel(url: str, workers: int = 3):
    print(f"\n{'='*60}")
    print(f"  Тест 4: Параллельные запросы ({workers} одновременно)")
    print(f"{'='*60}")
    results = [None] * workers
    threads = []

    def run(i):
        results[i] = single_request(url, QUESTIONS[i % len(QUESTIONS)], i)

    t0 = time.time()
    for i in range(workers):
        t = threading.Thread(target=run, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    total = round(time.time() - t0, 2)

    ok = sum(1 for r in results if r and r["status"] == "ok")
    errors = sum(1 for r in results if r and r["status"] == "error")
    rate_limited = sum(1 for r in results if r and r["status"] == "rate_limited")
    print(f"  OK: {ok} | Ошибок: {errors} | Rate limited: {rate_limited}")
    print(f"  Общее время (параллельно): {total}с")
    for r in results:
        if r:
            status = "✓" if r["status"] == "ok" else ("⚡" if r["status"] == "rate_limited" else "✗")
            print(f"    {status} [{r['idx']}] {r['elapsed']}с — {r['status']}")


def test_rate_limit(url: str):
    print(f"\n{'='*60}")
    print(f"  Тест 5: Rate limit (быстрые запросы)")
    print(f"{'='*60}")
    # Шлём быстрые лёгкие health-запросы чтобы проверить rate limit на /chat
    # Используем маленький max_tokens чтобы было быстро
    results = []
    for i in range(5):
        r = _http.post(f"{url}/chat", json={
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 10,
        }, timeout=30)
        results.append(r.status_code)
        print(f"  Запрос {i+1}: HTTP {r.status_code}")
    ok = results.count(200)
    limited = results.count(429)
    print(f"  Итог: {ok} OK, {limited} rate-limited")


def main():
    parser = argparse.ArgumentParser(description="Тест LLM-сервиса")
    parser.add_argument("--url", default="http://localhost:8030", help="URL сервиса")
    parser.add_argument("--workers", type=int, default=3, help="Параллельных запросов")
    parser.add_argument("--skip-parallel", action="store_true")
    args = parser.parse_args()

    print(f"\n🧪 Тестируем LLM-сервис: {args.url}")
    test_health(args.url)
    test_info(args.url)
    test_sequential(args.url)
    if not args.skip_parallel:
        test_parallel(args.url, args.workers)
    test_rate_limit(args.url)
    print(f"\n✅ Все тесты завершены.")


if __name__ == "__main__":
    main()
