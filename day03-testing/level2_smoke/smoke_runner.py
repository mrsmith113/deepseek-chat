#!/usr/bin/env python3
"""
smoke_runner.py — сам протыкивает UI (Playwright) по сценариям scenarios.md.

Что делает:
  1. Поднимает smoke_app (uvicorn) на 127.0.0.1:8799.
  2. Прогоняет S1–S5: кликает, заполняет формы, проверяет результат.
  3. На КАЖДЫЙ шаг — скриншот в screenshots/.
  4. Пишет отчёт SMOKE_REPORT.md: pass/fail по шагам + где сломалось.
  5. Гасит сервер.

Запуск: .venv/bin/python level2_smoke/smoke_runner.py
Аналог «агент через Playwright MCP» — здесь тот же Playwright, но headless и
скриптом, чтобы прогон был воспроизводим и попадал в отчёт.
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
BASE = "http://127.0.0.1:8799"
REPORT = HERE / "SMOKE_REPORT.md"

results: list[dict] = []
_step_no = 0


def shot(page: Page, name: str) -> str:
    global _step_no
    _step_no += 1
    fn = f"{_step_no:02d}_{name}.png"
    page.screenshot(path=str(SHOTS / fn))
    return fn


def run_scenario(page: Page, sid: str, title: str, steps) -> None:
    """steps: список (описание, callable(page)->str|None). Возврат = ошибка."""
    rec = {"id": sid, "title": title, "steps": [], "ok": True}
    for desc, fn in steps:
        entry = {"desc": desc, "status": "pass", "shot": None, "error": None}
        try:
            fn(page)
            entry["shot"] = shot(page, f"{sid}_{len(rec['steps'])}")
        except Exception as e:                       # noqa: BLE001
            entry["status"] = "fail"
            entry["error"] = f"{type(e).__name__}: {e}"
            try:
                entry["shot"] = shot(page, f"{sid}_{len(rec['steps'])}_FAIL")
            except Exception:
                pass
            rec["ok"] = False
            rec["steps"].append(entry)
            break
        rec["steps"].append(entry)
    results.append(rec)
    print(f"  {'✅' if rec['ok'] else '❌'} {sid} {title}")


# ---------- шаги-хелперы ----------

def login(page: Page, user="admin", pw="secret"):
    page.goto(BASE + "/")
    page.fill('[data-testid=login-user]', user)
    page.fill('[data-testid=login-pass]', pw)
    page.click('[data-testid=login-submit]')


def expect_text(page: Page, selector: str, needle: str):
    page.wait_for_selector(selector, timeout=4000)
    txt = page.text_content(selector) or ""
    assert needle in txt, f"в {selector} ждали '{needle}', получили '{txt.strip()}'"


# ---------- сценарии ----------

def scenarios(page: Page):
    # S1 — логин happy path
    run_scenario(page, "S1", "Логин (happy path)", [
        ("Открыть форму входа", lambda p: p.goto(BASE + "/")),
        ("Ввести admin/secret и войти", lambda p: login(p)),
        ("На /items виден заголовок", lambda p: expect_text(p, "h1", "Заявки ТН ВЭД")),
    ])

    # сброс состояния перед CRUD
    urllib.request.urlopen(BASE + "/__reset__", data=b"", timeout=5)
    login(page)

    # S2 — создать → появилась
    def add(p, good, code):
        p.fill('[data-testid=good]', good)
        p.fill('[data-testid=code]', code)
        p.click('[data-testid=add]')

    run_scenario(page, "S2", "Создать заявку → появилась", [
        ("Список пуст, счётчик (0)", lambda p: expect_text(p, '[data-testid=count]', "(0)")),
        ("Добавить дрон/8525893000", lambda p: add(p, "дрон с камерой", "8525893000")),
        ("Карточка #1 видна", lambda p: expect_text(p, '[data-testid=item-1]', "дрон с камерой")),
        ("Счётчик стал (1)", lambda p: expect_text(p, '[data-testid=count]', "(1)")),
    ])

    # S3 — вторая → счётчик растёт
    run_scenario(page, "S3", "Вторая заявка → счётчик растёт", [
        ("Добавить роутер/8517620009", lambda p: add(p, "роутер TP-Link", "8517620009")),
        ("Счётчик (2)", lambda p: expect_text(p, '[data-testid=count]', "(2)")),
        ("Карточка #2 видна", lambda p: expect_text(p, '[data-testid=item-2]', "роутер TP-Link")),
    ])

    # S4 — удалить → исчезла
    run_scenario(page, "S4", "Удалить заявку → исчезла", [
        ("Удалить #1", lambda p: p.click('[data-testid=del-1]')),
        ("Счётчик (1)", lambda p: expect_text(p, '[data-testid=count]', "(1)")),
        ("Карточки #1 больше нет",
         lambda p: (_ for _ in ()).throw(AssertionError("карточка #1 осталась"))
         if p.query_selector('[data-testid=item-1]') else None),
        ("Карточка #2 на месте", lambda p: expect_text(p, '[data-testid=item-2]', "роутер TP-Link")),
    ])

    # S5 — неверный пароль (negative)
    def logout_then_bad(p):
        p.goto(BASE + "/logout")
        login(p, "admin", "wrong")

    run_scenario(page, "S5", "Неверный пароль (negative)", [
        ("Logout + вход admin/wrong", logout_then_bad),
        ("Показана ошибка входа",
         lambda p: expect_text(p, '[data-testid=login-error]', "Неверный")),
        ("Без сессии /items не пускает — редирект на вход",
         lambda p: (p.goto(BASE + "/items"),
                    expect_text(p, '[data-testid=login-submit]', "Войти"))[-1]),
    ])


# ---------- запуск сервера + отчёт ----------

def wait_up(url: str, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def write_report():
    total_steps = sum(len(r["steps"]) for r in results)
    passed_steps = sum(1 for r in results for s in r["steps"] if s["status"] == "pass")
    ok_scen = sum(1 for r in results if r["ok"])
    lines = [
        "# Smoke-отчёт (Level 2) — UI через Playwright",
        "",
        f"- Сценариев: **{ok_scen}/{len(results)}** прошли",
        f"- Шагов: **{passed_steps}/{total_steps}** зелёных",
        f"- Мишень: `smoke_app.py` (CRUD «Заявки ТН ВЭД»)",
        "",
        "| Сценарий | Итог | Шагов ok |",
        "|---|---|---|",
    ]
    for r in results:
        ok = sum(1 for s in r["steps"] if s["status"] == "pass")
        lines.append(f"| {r['id']} {r['title']} | {'✅' if r['ok'] else '❌'} | {ok}/{len(r['steps'])} |")
    lines.append("")
    for r in results:
        lines.append(f"## {r['id']} — {r['title']}  {'✅' if r['ok'] else '❌'}")
        for s in r["steps"]:
            mark = "✅" if s["status"] == "pass" else "❌"
            lines.append(f"- {mark} {s['desc']}")
            if s["shot"]:
                lines.append(f"  - 📸 `screenshots/{s['shot']}`")
            if s["error"]:
                lines.append(f"  - ⚠️ **упало:** {s['error']}")
                lines.append(f"  - 🔎 **где смотреть:** UI-состояние на скрине выше + selector из шага")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return ok_scen, len(results), passed_steps, total_steps


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "smoke_app:app", "--port", "8799", "--log-level", "warning"],
        cwd=str(HERE),
    )
    try:
        if not wait_up(BASE + "/"):
            print("❌ сервер не поднялся")
            return 2
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 900, "height": 700})
            scenarios(page)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    ok_s, tot_s, ok_st, tot_st = write_report()
    print(f"\nСценарии: {ok_s}/{tot_s} | шаги: {ok_st}/{tot_st}")
    print(f"Отчёт: {REPORT}")
    return 0 if ok_s == tot_s else 1


if __name__ == "__main__":
    raise SystemExit(main())
