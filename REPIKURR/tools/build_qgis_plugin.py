#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
round47, блок B4: сборка публикуемого `pikurr_qgis.zip` из исходников
`pikurr_qgis/`, а не руками. До этого раунда архив в
`REPIKURR/repikurr/public/pikurr_qgis.zip` был закоммичен вручную и мог
разойтись с исходниками незаметно.

Пишет рядом `pikurr_qgis.sha256` (контрольная сумма архива) и печатает
версию (из metadata.txt) — используются `smoke.mjs`/`healthcheck.py`
для проверки дрейфа между тем, что опубликовано, и тем, что собирается
из текущих исходников (`--check`).

Использование:
    python3 build_qgis_plugin.py                  # собрать в public/
    python3 build_qgis_plugin.py --check           # сверить, не писать
    python3 build_qgis_plugin.py --out DIR         # собрать в DIR
"""
import argparse
import configparser
import hashlib
import io
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = REPO_ROOT / "pikurr_qgis"
DEFAULT_OUT_DIR = REPO_ROOT / "REPIKURR" / "repikurr" / "public"
ZIP_NAME = "pikurr_qgis.zip"
SHA_NAME = "pikurr_qgis.sha256"

# Не публикуется: справочная документация (не часть плагина),
# компилированный кеш, тесты, служебные файлы разработки.
EXCLUDE_DIRS = {"help", "__pycache__", "tests", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc"}
EXCLUDE_NAMES = {"PROTOTYPE_NOTICE.md"}


def read_version():
    cfg = configparser.ConfigParser()
    cfg.read(PLUGIN_SRC / "metadata.txt", encoding="utf-8")
    return cfg.get("general", "version", fallback="0.0.0")


def iter_plugin_files():
    for path in sorted(PLUGIN_SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(PLUGIN_SRC)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        if path.name in EXCLUDE_NAMES:
            continue
        yield path, rel


def build_zip_bytes():
    """Собирает архив в памяти — воспроизводимо (фиксированные mtime у
    записей), чтобы --check сравнивал по содержимому, не по дате сборки."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, rel in iter_plugin_files():
            arcname = str(Path("pikurr_qgis") / rel)
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                     help=f"каталог назначения (по умолчанию {DEFAULT_OUT_DIR})")
    ap.add_argument("--check", action="store_true",
                     help="не писать файлы — сравнить с уже опубликованными")
    args = ap.parse_args()

    version = read_version()
    zip_bytes = build_zip_bytes()
    sha256 = hashlib.sha256(zip_bytes).hexdigest()

    zip_path = args.out / ZIP_NAME
    sha_path = args.out / SHA_NAME

    if args.check:
        problems = []
        if not zip_path.exists():
            problems.append(f"отсутствует {zip_path}")
        else:
            published = zip_path.read_bytes()
            published_sha = hashlib.sha256(published).hexdigest()
            if published_sha != sha256:
                problems.append(
                    f"{zip_path} НЕ соответствует исходникам pikurr_qgis/ "
                    f"(опубликован {published_sha[:12]}, из исходников {sha256[:12]})"
                )
        if problems:
            for p in problems:
                print(f"[build_qgis_plugin] РАСХОЖДЕНИЕ: {p}", file=sys.stderr)
            return 1
        print(f"[build_qgis_plugin] {zip_path} в синхроне с исходниками "
              f"(версия {version}, sha256 {sha256[:12]}...)")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(zip_bytes)
    sha_path.write_text(f"{sha256}  {ZIP_NAME}\n", encoding="utf-8")
    print(f"[build_qgis_plugin] записано {zip_path} "
          f"(версия {version}, sha256 {sha256[:12]}..., {len(zip_bytes)} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
