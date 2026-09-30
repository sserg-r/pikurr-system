#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка каталога носителя с исходными текстами (для ведомости носителя).

Берёт из git-отслеживаемых файлов репозитория выбранный состав, копирует его
в указанный каталог, повторно проверяет РЕЗУЛЬТАТ на шаблоны секретов и
печатает дерево с размерами в байтах (для заполнения ведомости).

Состав (см. docs/facts/source-deposit.md):
  включается — исходные тексты контуров обработки и публикации, фронтенд,
  плагин QGIS (без tests/ и help/), шаблоны *.example / .env_example,
  инструменты; при указании --onnx — файл модели;
  не включается — docs/, CLAUDE.md, тесты плагина, производные архивы
  (public/pikurr_qgis.zip, help/), разовые диагностические сценарии,
  архив прежнего инференса, служебные файлы репозитория.

Особый случай: datastore.xml GeoServer (пароль БД открытым текстом) копируется
с очищенным паролем (`plain:` без значения), оригинал не изменяется.

Использование:
    python3 REPIKURR/tools/build_deposit.py --out <каталог> [--onnx <файл.onnx>]

Каталог --out должен быть пустым или несуществующим. Код возврата: 0 — секретов
в результате не найдено; 1 — найдены (каталог остаётся для разбора);
2 — ошибка использования.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDE_PREFIXES = (
    "docs/",
    "CLAUDE.md",
    ".gitignore",
    "pikurr_qgis/tests/",
    "pikurr_qgis/help/",
    "pikurr_qgis/PROTOTYPE_NOTICE.md",
    "REPIKURR/repikurr/public/pikurr_qgis.zip",
    "REPIKURR/tools/round37_",        # разовые диагностические сценарии
    "REPIKURR/tools/smoke/round50_",  # разовые диагностические сценарии
    "PIKURR/src/services/_archive/",  # путь отката на прежний способ инференса
    "REPIKURR/repikurr/.env",  # локальная настройка разработки (единственная переменная, пустая)
)

# Файлы с секретами/значениями по умолчанию, копируемые в очищенном виде:
# путь -> список (regex, замена). Оригиналы не изменяются.
SANITIZE = {
    "REPIKURR/geoserver_data/workspaces/pikurr/postgis_pikurr/datastore.xml": [
        (re.compile(r'(<entry key="passwd">)(?:plain|crypt\d?):[^<]*(</entry>)'), r"\1plain:\2"),
    ],
    # шаблон окружения: значение по умолчанию заменяется пустым
    ".env_example": [
        (re.compile(r"(?m)^(POSTGRES_PASSWORD=).*$"), r"\1"),
    ],
    # в комментарии упоминались прежние значения по умолчанию
    "REPIKURR/.env.example": [
        (re.compile(r"(?m)^(# round21, B1: раньше ).*$"), r"\1в шаблоне были значения паролей по умолчанию; теперь значения задаются оператором"),
    ],
}

# Шаблоны секретов для проверки результата.
SECRET_PATTERNS = [
    ("приватный ключ", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("ключ AWS", re.compile(r"AKIA[0-9A-Z]{12,}")),
    ("ключ Google API", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("токен GitHub", re.compile(r"ghp_[0-9A-Za-z]{20,}")),
    ("токен Slack", re.compile(r"xox[abp]-[0-9A-Za-z-]{10,}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")),
    ("private_key в JSON", re.compile(r'"private_key"\s*:\s*"')),
    ("пароль GeoServer (plain:/crypt:) со значением", re.compile(r"(?:plain|crypt\d?):[^<\s\"'&]+")),
    ("присвоение секрета литералом", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY)\b\s*[=:]\s*['\"]?"
        r"(?![$<{]|your_|token_here|example|changeme|None\b|null\b|os\.|self\.|settings\.|_required_env|str\b|Path\b|FRONTEND_DB|\"|')"
        r"[A-Za-z0-9!@#%^&*_./+-]{3,}")),
]
# Имена файлов, которые в результате быть не должны вообще.
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env|.*\.env|credentials|.*\.jceks|id_rsa.*|.*\.pem|passwd|users\.xml|tomcat_pass\.txt)$")
ALLOWED_TEMPLATE_NAMES = re.compile(r"\.example$|(^|/)\.env_example$|(^|/)\.env\.example$")
TEXT_EXT_SKIP = {".png", ".jpg", ".zip", ".onnx", ".gz", ".ico"}


def git_files() -> list[str]:
    out = subprocess.check_output(["git", "-C", str(REPO_ROOT), "ls-files"], text=True)
    return [f for f in out.splitlines() if f]


def selected(files: list[str]) -> list[str]:
    res = []
    for f in files:
        if any(f == p or f.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        if not (REPO_ROOT / f).is_file():
            continue
        res.append(f)
    return res


def copy_files(files: list[str], out: Path) -> None:
    for f in files:
        src = REPO_ROOT / f
        dst = out / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        if f in SANITIZE:
            text = src.read_text(encoding="utf-8")
            n = 0
            for rx, repl in SANITIZE[f]:
                text, k = rx.subn(repl, text)
                n += k
            dst.write_text(text, encoding="utf-8")
            print(f"[очищен] {f} (замен: {n})")
        else:
            shutil.copy2(src, dst)


def scan(out: Path) -> list[str]:
    findings = []
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        if FORBIDDEN_NAMES.search(rel) and not ALLOWED_TEMPLATE_NAMES.search(rel):
            findings.append(f"{rel}: запрещённое имя файла")
            continue
        if p.suffix.lower() in TEXT_EXT_SKIP:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in SECRET_PATTERNS:
                if rx.search(line):
                    findings.append(f"{rel}:{lineno}: {name}")
    return findings


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def print_tree(root: Path, lines: list[str], prefix: str = "") -> None:
    entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, p in enumerate(entries):
        last = i == len(entries) - 1
        branch = "└─ " if last else "├─ "
        size = p.stat().st_size if p.is_file() else dir_size(p)
        lines.append(f"{prefix}{branch}{p.name}\t{size}")
        if p.is_dir():
            print_tree(p, lines, prefix + ("   " if last else "│  "))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="каталог носителя (пустой или несуществующий)")
    ap.add_argument("--onnx", help="файл модели two_opset13.onnx (копируется в models/onnx/)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"Каталог {out} не пуст", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    files = selected(git_files())
    copy_files(files, out)
    if args.onnx:
        src = Path(args.onnx)
        if not src.is_file():
            print(f"Файл модели не найден: {src}", file=sys.stderr)
            return 2
        dst = out / "models" / "onnx" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[модель] {dst.relative_to(out)} sha256={hashlib.sha256(dst.read_bytes()).hexdigest()}")

    findings = scan(out)
    total = dir_size(out)
    lines = [f"{out.name}\t{total}"]
    print_tree(out, lines)
    tree_path = out.parent / f"{out.name}_tree.txt"
    tree_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Файлов: {sum(1 for p in out.rglob('*') if p.is_file())}, байт: {total}")
    print(f"Дерево с размерами: {tree_path}")

    if findings:
        print("НАЙДЕНЫ ВОЗМОЖНЫЕ СЕКРЕТЫ В РЕЗУЛЬТАТЕ:", file=sys.stderr)
        for f in findings:
            print("  " + f, file=sys.stderr)
        return 1
    print("Проверка на секреты: совпадений нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
