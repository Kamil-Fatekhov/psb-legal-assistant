"""Сквозная проверка интерфейса в настоящем браузере (Playwright).

    pip install -r requirements-dev.txt && python -m playwright install chromium
    python scripts/e2e_browser.py [http://127.0.0.1:8000]

Сервер должен быть запущен в демо-режиме (ASSISTANT_MODE=mock): сценарии
сбоя и уточнения берутся из мока. Скриншоты сохраняются в e2e-screens/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
SHOTS = Path("e2e-screens")
QUESTION = "Сколько платить за Северный Склад и когда?"


def ask(page: Page, text: str) -> None:
    before = page.locator(".msg-assistant").count()
    page.fill("#question", text)
    page.keyboard.press("Enter")
    expect(page.locator(".msg-assistant:not(:has(.thinking))")).to_have_count(before + 1, timeout=150_000)


def desktop(browser, problems: list[str]) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: problems.append(f"JS: {e}"))
    # 503 и 404 тест вызывает намеренно; браузер пишет о них в консоль — это не ошибка JS.
    page.on("console", lambda m: problems.append(f"console: {m.text}")
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.goto(BASE)
    expect(page.locator("#empty")).to_be_visible()
    page.screenshot(path=SHOTS / "1-start.png")

    # Основной сценарий: ответ, сноски, источник с обоими пунктами
    page.get_by_role("button", name=QUESTION).click()
    answer = page.locator(".msg-assistant").last
    expect(answer).to_have_class("msg msg-assistant status-answered")
    expect(answer).to_contain_text("450 000")
    expect(answer.locator(".cite")).to_have_count(2)
    answer.locator(".cite").first.click()
    body = page.locator("#doc-body")
    expect(body).to_contain_text("3.1")
    expect(body).to_contain_text("3.2")
    assert "#source=" in page.url, "ссылка на источник не попала в адрес"
    page.screenshot(path=SHOTS / "2-answer-and-source.png")

    # Прямая ссылка на источник открывается после перезагрузки, диалог сохраняется
    page.reload()
    expect(page.locator("#doc-body")).to_contain_text("3.2")
    expect(page.locator(".msg-user")).to_have_count(1)

    # Сбой зависимости: отдельное сообщение и кнопка повтора; ошибка не теряется
    ask(page, "#сбой")
    expect(page.locator(".status-error")).to_contain_text("Сервис временно недоступен")
    page.get_by_role("button", name="Повторить запрос").click()
    expect(page.locator(".status-error")).to_have_count(1)
    ask(page, "Какие условия в договоре с Альфа?")
    expect(page.locator(".status-error")).to_have_count(1)
    expect(page.locator(".status-clarification_needed")).to_contain_text("Альфа-Трейдинг")
    page.screenshot(path=SHOTS / "3-error-and-clarification.png")

    # Текст пользователя выводится как текст, а не как HTML
    payload = '<img src=x onerror="window.__xss=1">'
    ask(page, payload)
    expect(page.locator(".msg-user").last).to_have_text(payload)
    assert page.locator(".log img").count() == 0, "HTML из вопроса попал в разметку"

    # Неизвестный ID по прямой ссылке — понятное сообщение
    page.goto(BASE + "/#source=" + "нет-такого%3Abase%3A0")
    expect(page.locator(".doc-error")).to_contain_text("нет в каталоге")

    # Новый диалог очищает историю
    page.get_by_role("button", name="Новый диалог").click()
    expect(page.locator("#empty")).to_be_visible()
    page.close()


def mobile(browser, problems: list[str]) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page.on("pageerror", lambda e: problems.append(f"JS mobile: {e}"))
    page.goto(BASE)
    ask(page, QUESTION)
    expect(page.locator("#source-panel")).to_be_hidden()
    page.screenshot(path=SHOTS / "4-mobile-chat.png")
    page.locator(".cite").first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator("#doc-body")).to_contain_text("3.1")
    page.screenshot(path=SHOTS / "5-mobile-source.png")
    page.get_by_role("button", name="К диалогу").click()
    expect(page.locator("#source-panel")).to_be_hidden()
    page.close()


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        chrome = os.getenv("CHROME_PATH")
        browser = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        try:
            desktop(browser, problems)
            mobile(browser, problems)
        finally:
            browser.close()
    if problems:
        print("Ошибки в консоли браузера:\n  " + "\n  ".join(problems))
        return 1
    print(f"Интерфейс: все сценарии прошли. Скриншоты: {SHOTS.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
