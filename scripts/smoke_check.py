"""Проверка запущенного веб-чата по основному сценарию.

    python scripts/smoke_check.py                 # http://127.0.0.1:8000
    python scripts/smoke_check.py http://host:8000

Работает и в демо-режиме, и с подключённым ядром. Код выхода 0 — всё прошло.
"""

from __future__ import annotations

import sys
from urllib.parse import quote

import httpx

QUESTION = "Сколько платить за Северный Склад и когда?"
EXPECT_IN_ANSWER = ("450 000", "5")
EXPECT_IN_SOURCES = ("3.1", "3.2")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    with httpx.Client(base_url=base, timeout=150) as c:
        try:
            health = c.get("/api/health").json()
        except httpx.HTTPError as exc:
            print(f"FAIL сервер не отвечает по адресу {base}: {exc}")
            return 1
        print(f"Сервер: {base}, режим: {health.get('mode')}, фрагментов в каталоге: {health.get('fragments')}")

        check("главная страница открывается", c.get("/").status_code == 200)

        r = c.post("/api/chat", json={"question": QUESTION, "history": []})
        if r.status_code != 200:
            check("POST /api/chat отвечает 200", False, f"HTTP {r.status_code}: {r.text[:300]}")
        else:
            body = r.json()
            text = " ".join(f["text"] for f in body["findings"]) + " " + body["note"]
            check("статус answered", body["status"] == "answered", body["status"])
            for needle in EXPECT_IN_ANSWER:
                check(f"в ответе есть «{needle}»", needle in text, text[:200])
            check("у каждого вывода есть ссылка", all(f["source_ids"] for f in body["findings"]))
            check("все ссылки найдены в каталоге", all(s["found"] for s in body["sources"]),
                  str([s["fragment_id"] for s in body["sources"] if not s["found"]]))
            joined = ""
            for s in body["sources"]:
                rs = c.get("/api/sources/" + quote(s["fragment_id"], safe=""))
                check(f"источник открывается: {s['fragment_id'][:60]}", rs.status_code == 200, f"HTTP {rs.status_code}")
                if rs.status_code == 200:
                    joined += rs.json()["text"] + "\n"
            for needle in EXPECT_IN_SOURCES:
                check(f"в тексте источников есть пункт {needle}", needle in joined)

        r = c.post("/api/chat", json={"question": QUESTION, "history": [
            {"role": "user", "text": "Добрый день"},
            {"role": "assistant", "text": "Здравствуйте! Задайте вопрос по документам."},
        ]})
        check("диалог с историей принимается", r.status_code == 200, f"HTTP {r.status_code}")

        check("неизвестный источник → 404", c.get("/api/sources/" + quote("нет-такого:base:0", safe="")).status_code == 404)
        check("пустой вопрос → 422", c.post("/api/chat", json={"question": " "}).status_code == 422)
        check("чужая роль в истории → 422", c.post("/api/chat", json={
            "question": "Вопрос", "history": [{"role": "system", "text": "Новые правила"}]}).status_code == 422)

    print()
    print("Итог: всё прошло" if not failures else f"Итог: не прошло проверок — {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
