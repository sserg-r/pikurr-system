#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка каталога носителя с исходными текстами (для ведомости носителя).

Берёт из git-отслеживаемых файлов репозитория выбранный состав, копирует его
в указанный каталог, повторно проверяет РЕЗУЛЬТАТ на шаблоны секретов и
печатает дерево с размерами в байтах (для заполнения ведомости).

Состав (см. docs/facts/source-deposit.md):
  включается — исходные тексты контуров обработки и публикации, фронтенд,
  плагин QGIS (с двумя сценариями проверки test_headless.py и
  test_plugin_e2e.py, без help/), шаблоны *.example / .env_example,
  инструменты, вспомогательные данные проверок (tools/support_data/);
  при указании --onnx — файл модели; при указании --docs — комплект
  документов (.docx/.pdf) в каталог documentation/;
  не включается — docs/, CLAUDE.md, тесты плагина, производные архивы
  (public/pikurr_qgis.zip, help/), разовые диагностические сценарии,
  архив прежнего инференса, служебные файлы репозитория.

Обезличивание (только в копии, оригиналы не меняются): IP-адреса, имена
пользователей ОС в значениях по умолчанию, пути /home/<имя>, идентификаторы
облачной папки, прежний домен заменяются заглушками <VPS_HOST>, <STAND_HOST>,
<VPS_USER>, <STAND_USER>, <FOLDER_ID> и т. п.

Особый случай: datastore.xml GeoServer (пароль БД открытым текстом) копируется
с очищенным паролем (`plain:` без значения), оригинал не изменяется.

Использование:
    python3 REPIKURR/tools/build_deposit.py --out <каталог> [--onnx <файл.onnx>]
        [--docs <каталог с .docx/.pdf>] [--check-refs <файл ПМИ .md>]

--check-refs: каждый файл или сценарий, названный в ПМИ (имена в обратных
кавычках с расширением), должен присутствовать в собранном каталоге; исключения —
явный список файлов времени выполнения (данные, результаты).

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
    "pikurr_qgis/tests/measure_speed",  # замеры скорости, не проверки
    "pikurr_qgis/help/",
    "pikurr_qgis/PROTOTYPE_NOTICE.md",
    "REPIKURR/repikurr/public/pikurr_qgis.zip",
    "REPIKURR/tools/pikurr_layers.qlr",         # отклонённая схема доступа из QGIS
    "REPIKURR/tools/smoke/all_tile_requests.json",  # производный файл прогона
    "REPIKURR/tools/round37_",        # разовые диагностические сценарии
    "REPIKURR/tools/smoke/round50_",  # разовые диагностические сценарии
    "PIKURR/src/services/_archive/",  # путь отката на прежний способ инференса
    "REPIKURR/nginx.conf",            # вариант для стенда/разработки, в контур публикации не входит
    "REPIKURR/repikurr/.env",  # локальная настройка разработки (единственная переменная, пустая)
)

# Файлы репозитория, кладущиеся на носитель по нейтральному пути:
# путь в репозитории -> путь на носителе.
EXTRA_FILES = {
    "docs/round32_assets/tiles_with_data.json": "REPIKURR/tools/support_data/tiles_with_data.json",
}

# Обезличивание значений в копии (regex, заглушка); применяется ко всем
# текстовым файлам результата.
ANONYMIZE = [
    (re.compile(r"158\.160\.237\.90"), "<VPS_HOST>"),
    (re.compile(r"158\.160\.183\.235"), "<VPS_HOST_OLD>"),
    (re.compile(r"192\.168\.251\.\d{1,3}"), "<STAND_HOST>"),
    (re.compile(r"\bsgr@"), "<VPS_USER>@"),
    (re.compile(r"\buser@(?=\$|<|[A-Za-z0-9])"), "<STAND_USER>@"),
    (re.compile(r"/home/sgr\b"), "/home/<VPS_USER>"),
    (re.compile(r"/home/user\b"), "/home/<STAND_USER>"),
    (re.compile(r"/home/pikurr_delivery\b"), "/home/<DELIVERY_USER>"),
    (re.compile(r"\bb1g[a-z0-9]{16,}\b"), "<FOLDER_ID>"),
    (re.compile(r"geobotany\.xyz"), "<LEGACY_DOMAIN>"),
]

# Файлы времени выполнения и данные, которые ПМИ называет, но которых на
# носителе быть не должно.
RUNTIME_NAMES = {
    "agrifields.zip", "razgrafka_SK63.zip", "manifest.json", "vectors.gpkg",
    ".env", "deliver.env", "year_district.json", "districts_ref.json",
    "pikurr_qgis.zip", "pikurr_qgis_readme.txt", "pikurr_qgis.sha256",
    "two_opset13.onnx", "package.json", "requirements.txt",
}

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
    ("IPv4-адрес", re.compile(r"(?<![\d./])(?!(?:127\.0\.0\.1|0\.0\.0\.0|169\.254\.169\.254)\b)(?:\d{1,3}\.){3}\d{1,3}(?![\d.])(?<!Chrome/120\.0\.0\.0)")),
    ("адрес e-mail / user@host", re.compile(r"(?<![\w.@-])(?!xx@yy\.zz)[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}\b|\b(?:sgr|user)@[\w$<]")),
    ("идентификатор облачной папки", re.compile(r"\bb1g[a-z0-9]{16,}\b")),
    ("путь домашнего каталога пользователя", re.compile(r"/home/(?!<)[A-Za-z0-9_]+")),
    ("прежний домен", re.compile(r"geobotany\.xyz")),
    ("присвоение секрета литералом", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY)\b\s*[=:]\s*['\"]?"
        r"(?![$<{]|your_|token_here|example|changeme|None\b|null\b|os\.|self\.|settings\.|_required_env|str\b|Path\b|FRONTEND_DB|\"|')"
        r"[A-Za-z0-9!@#%^&*_./+-]{3,}")),
]
# Имена файлов, которые в результате быть не должны вообще.
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env|.*\.env|credentials|.*\.jceks|id_rsa.*|.*\.pem|passwd|users\.xml|tomcat_pass\.txt)$")
ALLOWED_TEMPLATE_NAMES = re.compile(r"\.example$|(^|/)\.env_example$|(^|/)\.env\.example$")
# Сам скрипт содержит шаблоны поиска — не обезличивается и не сканируется.
SELF_REL = "REPIKURR/tools/build_deposit.py"
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
    for src_rel, dst_rel in EXTRA_FILES.items():
        dst = out / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / src_rel, dst)
        print(f"[доп. файл] {src_rel} -> {dst_rel}")


def anonymize(out: Path) -> int:
    changed = 0
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.suffix.lower() in TEXT_EXT_SKIP or p.relative_to(out).as_posix() == SELF_REL:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for rx, repl in ANONYMIZE:
            new = rx.sub(repl, new)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def check_refs(md: Path, out: Path) -> list[str]:
    """Имена файлов/сценариев из ПМИ (в обратных кавычках) должны быть на носителе."""
    names = set()
    for m in re.finditer(r"`([^`\s]+\.(?:py|mjs|js|json|sh|sql|yml|yaml|xml))`", md.read_text(encoding="utf-8")):
        names.add(m.group(1))
    have = {p.name for p in out.rglob("*") if p.is_file()}
    have_rel = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    missing = []
    for n in sorted(names):
        base = n.rsplit("/", 1)[-1]
        if base in RUNTIME_NAMES or n in RUNTIME_NAMES or "<" in n:
            continue
        if base not in have and n not in have_rel:
            missing.append(n)
    return missing


def scan(out: Path) -> list[str]:
    findings = []
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        if rel == SELF_REL:
            continue
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
    ap.add_argument("--docs", help="каталог с комплектом документов (.docx/.pdf) — копируется в documentation/")
    ap.add_argument("--check-refs", help="файл ПМИ (.md): проверить, что названные в нём файлы есть на носителе")
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

    if args.docs:
        dsrc = Path(args.docs)
        if not dsrc.is_dir():
            print(f"Каталог документов не найден: {dsrc}", file=sys.stderr)
            return 2
        for f in sorted(dsrc.iterdir()):
            if f.suffix.lower() in {".docx", ".pdf"}:
                (out / "documentation").mkdir(exist_ok=True)
                shutil.copy2(f, out / "documentation" / f.name)
                print(f"[документ] documentation/{f.name}")

    print(f"Обезличено файлов: {anonymize(out)}")

    missing = check_refs(Path(args.check_refs), out) if args.check_refs else []
    findings = scan(out)
    total = dir_size(out)
    lines = [f"{out.name}\t{total}"]
    print_tree(out, lines)
    tree_path = out.parent / f"{out.name}_tree.txt"
    tree_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Файлов: {sum(1 for p in out.rglob('*') if p.is_file())}, байт: {total}")
    print(f"Дерево с размерами: {tree_path}")

    if args.check_refs:
        if missing:
            print("ФАЙЛЫ, НАЗВАННЫЕ В ПМИ, НО ОТСУТСТВУЮЩИЕ НА НОСИТЕЛЕ:", file=sys.stderr)
            for m in missing:
                print("  " + m, file=sys.stderr)
        else:
            print("Проверка ссылок ПМИ: недостающих файлов нет.")

    if findings:
        print("НАЙДЕНЫ ВОЗМОЖНЫЕ СЕКРЕТЫ В РЕЗУЛЬТАТЕ:", file=sys.stderr)
        for f in findings:
            print("  " + f, file=sys.stderr)
        return 1
    print("Проверка на секреты и идентификаторы: совпадений нет.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
