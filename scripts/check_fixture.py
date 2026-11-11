"""Сверка фикстуры аренды с выданной базой знаний (задача C на день 1).

    python scripts/check_fixture.py              # ищет data/kb.zip или data/kb/
    python scripts/check_fixture.py path/to/kb.zip

Проверяет, что ID из fixtures/rent_case.json есть в каталоге A и что его
текст содержит оба пункта. Если нет — печатает фрагменты-кандидаты, чтобы
обновить фикстуру точным ID и текстом.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web.mock import DEFAULT_FIXTURE  # noqa: E402
from web.wiring import Settings, find_knowledge_base, load_corpus  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        kb = Path(sys.argv[1])
    else:
        kb = find_knowledge_base(Settings(data_dir=ROOT / "data"))
    if kb is None or not kb.exists():
        print("База знаний не найдена. Положите kb.zip в data/ или передайте путь аргументом.")
        return 2

    fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    corpus = load_corpus(kb)
    print(f"База: {kb}; фрагментов: {len(corpus.fragments)}")

    ok = True
    for source in fixture["sources"]:
        fid = source["fragment_id"]
        fragment = corpus.fragments.get(fid)
        if fragment is None:
            ok = False
            print(f"FAIL ID нет в каталоге: {fid}")
            continue
        missing = [n for n in fixture["expect"]["fragment_must_contain"] if n not in fragment.text]
        same = fragment.text == source["text"]
        print(f"{'OK  ' if not missing else 'FAIL'} {fid}")
        if missing:
            ok = False
            print(f"     в тексте нет: {missing}")
        if not same:
            print("     текст фикстуры отличается от базы — замените его точным текстом:")
            print("     " + json.dumps(fragment.text, ensure_ascii=False))

    if not ok:
        print("\nКандидаты (фрагменты с «450» и «3.2»):")
        for fragment in corpus.fragments.values():
            if "450" in fragment.text and "3.2" in fragment.text:
                print(f"  {fragment.fragment_id}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
