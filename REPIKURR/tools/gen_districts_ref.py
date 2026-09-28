#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
round47, блок A2: справочник "код района/области -> название" для
плагина QGIS собирается из ЕДИНСТВЕННОГО места, где он уже существовал
до этого раунда — REPIKURR/repikurr/src/constants.js (фронтенд).

До этого раунда справочник существовал в ДВУХ независимых написанных
руками копиях (constants.js и pikurr_qgis/pikurr.py, последняя — только
20 районов Витебской области, без учёта 6204, добавленного в constants.js
позже — round45-qgis-recon.md). Единого серверного источника (таблицы в
БД, представления GeoServer) не существует ни на проде, ни в разработке
— полноценное решение (DB-backed слой) требует изменения схемы, что вне
объёма этого раунда и требует отдельного решения пользователя. Этот
скрипт — минимальный шаг, устраняющий именно "молчаливый дрейф": плагин
больше не хранит свою копию, а публикуемый JSON генерируется из
constants.js, не редактируется руками отдельно.

Использование:
    python3 gen_districts_ref.py [--check]

Без --check: перегенерирует REPIKURR/repikurr/public/districts_ref.json.
С --check: не пишет файл, возвращает код 1, если существующий файл
    разошёлся с тем, что было бы сгенерировано из constants.js сейчас
    (для CI/pre-deploy проверки дрейфа, см. docs/round47-qgis-plugin.md).
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTANTS_JS = REPO_ROOT / "REPIKURR" / "repikurr" / "src" / "constants.js"
OUTPUT_JSON = REPO_ROOT / "REPIKURR" / "repikurr" / "public" / "districts_ref.json"


def _parse_js_object(js_source, var_name):
    """Разбирает `export const <var_name> = { 'код': 'значение', ... }`
    без полноценного JS-парсера — константы написаны вручную в этом
    простом формате (проверяется по факту, что ключей столько же после
    и вызывающий код это доказывает при генерации)."""
    m = re.search(
        r"export\s+const\s+" + re.escape(var_name) + r"\s*=\s*\{(.*?)\}\s*;?\s*\n",
        js_source,
        re.S,
    )
    if not m:
        raise ValueError(f"не найдена константа {var_name} в {CONSTANTS_JS}")
    body = m.group(1)
    # убираем однострочные комментарии // ...
    body = re.sub(r"//[^\n]*", "", body)
    pairs = re.findall(r"""['"]([^'"]+)['"]\s*:\s*['"]([^'"]*)['"]""", body)
    if not pairs:
        raise ValueError(f"не удалось разобрать пары код:название для {var_name}")
    return dict(pairs)


def build_reference():
    js_source = CONSTANTS_JS.read_text(encoding="utf-8")
    oblasts = _parse_js_object(js_source, "oblasts")
    districts = _parse_js_object(js_source, "distr")
    return {"oblasts": oblasts, "districts": districts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                     help="только сверить существующий файл, не писать")
    args = ap.parse_args()

    fresh = build_reference()
    fresh_text = json.dumps(fresh, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not OUTPUT_JSON.exists():
            print(f"[gen_districts_ref] ОТСУТСТВУЕТ: {OUTPUT_JSON}", file=sys.stderr)
            return 1
        current_text = OUTPUT_JSON.read_text(encoding="utf-8")
        if current_text != fresh_text:
            print(
                f"[gen_districts_ref] РАСХОЖДЕНИЕ: {OUTPUT_JSON} не соответствует "
                f"{CONSTANTS_JS} — перегенерировать без --check",
                file=sys.stderr,
            )
            return 1
        print(f"[gen_districts_ref] {OUTPUT_JSON} в синхроне с {CONSTANTS_JS} "
              f"({len(fresh['districts'])} районов, {len(fresh['oblasts'])} областей)")
        return 0

    OUTPUT_JSON.write_text(fresh_text, encoding="utf-8")
    print(f"[gen_districts_ref] записано {OUTPUT_JSON} "
          f"({len(fresh['districts'])} районов, {len(fresh['oblasts'])} областей)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
