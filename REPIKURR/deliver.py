#!/usr/bin/env python3
"""
Скрипт доставки пакета обновлений PIKURR на фронтенд-стек (REPIKURR).

Использование:
    python deliver.py [path/to/pikurr_update_*.zip]

Без аргумента — берёт последний ZIP из ../outputs/dist/.

Что делает:
  1. Распаковывает пакет, читает manifest.json (год, версия)
  2. Копирует TIF-файлы в data/geodata/{year}/
  3. Импортирует GPKG-слои в PostGIS (agrifields, razgrafka, assessment)
  4. Пересоздаёт view assessment_ready (SQL-скрипт из пакета)
  5. Перезагружает ImageMosaic-слой в GeoServer (REST API)
  6. Удаляет ZIP-пакет после успешной доставки

Примечание по продакшену:
  SQL-скрипт create_assessment_schema.sql включён в пакет самим PackageTask,
  поэтому скрипт самодостаточен — не нужен доступ к исходникам ETL-стека.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Конфигурация (переопределяется через переменные окружения)
# ---------------------------------------------------------------------------

FRONTEND_DB = {
    "host": os.getenv("FRONTEND_DB_HOST", "localhost"),
    "port": int(os.getenv("FRONTEND_DB_PORT", "5433")),
    "user": os.getenv("FRONTEND_DB_USER", "pikurr"),
    "password": os.getenv("FRONTEND_DB_PASSWORD", "pikurr"),
    "name": os.getenv("FRONTEND_DB_NAME", "pikurr"),
}

GEOSERVER_URL = os.getenv("GEOSERVER_URL", "http://localhost:8090/geoserver")
GEOSERVER_USER = os.getenv("GEOSERVER_USER", "admin")
GEOSERVER_PASSWORD = os.getenv("GEOSERVER_PASSWORD", "geoserver")
GEOSERVER_WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "pikurr")
GEOSERVER_COVERAGESTORE = os.getenv("GEOSERVER_COVERAGESTORE", "image_assessment")

SCRIPT_DIR = Path(__file__).resolve().parent
GEODATA_DIR = SCRIPT_DIR / "data" / "geodata"

# Папка с ZIP-пакетами по умолчанию.
# На сервере переопределяется через PIKURR_INBOX или env, либо через аргумент.
_inbox_env = os.getenv("PIKURR_INBOX")
DEFAULT_DIST_DIR = Path(_inbox_env) if _inbox_env else SCRIPT_DIR / "inbox"
# Fallback для локальной разработки: ../outputs/dist/
if not DEFAULT_DIST_DIR.exists():
    _fallback = SCRIPT_DIR.parent / "outputs" / "dist"
    if _fallback.exists():
        DEFAULT_DIST_DIR = _fallback

# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Шаги доставки
# ---------------------------------------------------------------------------

def find_latest_zip(dist_dir: Path) -> Path:
    zips = sorted(dist_dir.glob("pikurr_update_*.zip"))
    if not zips:
        raise FileNotFoundError(f"Нет ZIP-пакетов в {dist_dir}")
    return zips[-1]


def unpack(zip_path: Path, dest: Path) -> dict:
    """Распаковывает архив, возвращает manifest."""
    logger.info(f"Распаковываю {zip_path.name} → {dest}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)

    manifest_path = dest / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.json не найден в пакете")

    with open(manifest_path) as f:
        manifest = json.load(f)

    logger.info(
        f"Манифест: год={manifest['year']}, "
        f"версия={manifest['version']}, "
        f"создан={manifest['created_at']}"
    )
    return manifest


def copy_rasters(rasters_dir: Path) -> dict:
    """Копирует TIF из пакета в data/geodata/{year}/.

    Поддерживает два формата пакета:
    - новый: rasters/{year}/*.tif  (multi-year)
    - legacy: rasters/*.tif        (один год, берётся из manifest)

    Возвращает dict {year: кол-во_файлов}.
    """
    result = {}
    if not rasters_dir.exists():
        logger.warning(f"Папка растров в пакете не найдена: {rasters_dir}")
        return result

    # Проверяем формат: есть ли числовые подпапки?
    year_dirs = sorted(
        [d for d in rasters_dir.iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda d: int(d.name),
    )

    if year_dirs:
        # Новый формат: rasters/{year}/
        for year_dir in year_dirs:
            year = int(year_dir.name)
            dst = GEODATA_DIR / year_dir.name
            dst.mkdir(parents=True, exist_ok=True)
            tifs = list(year_dir.glob("*.tif")) + list(year_dir.glob("*.TIF"))
            for tif in tifs:
                shutil.copy2(tif, dst / tif.name)
            result[year] = len(tifs)
            logger.info(f"Скопировано {len(tifs)} TIF ({year}) → {dst}")
    else:
        # Legacy-формат: TIF лежат прямо в rasters/
        logger.warning("Обнаружен legacy-формат растров (без подпапок по годам).")
        return result  # без явного года не копируем — caller передаст год из manifest

    return result


def _ogr2ogr_cmd(pgpassword: str) -> tuple[list[str], bool]:
    """Возвращает (prefix, via_docker).

    via_docker=False: ['ogr2ogr'] — запуск на хосте, пароль через env.
    via_docker=True:  ['docker','exec',...] — запуск в GeoServer-контейнере,
                      пароль передаётся через -e PGPASSWORD.
    """
    import shutil as _shutil
    if _shutil.which("ogr2ogr"):
        return ["ogr2ogr"], False

    container = os.getenv("GEOSERVER_CONTAINER", "pikurr_srv_geoserver")
    check = subprocess.run(
        ["docker", "exec", container, "which", "ogr2ogr"],
        capture_output=True, text=True,
    )
    if check.returncode == 0:
        logger.info(f"ogr2ogr не найден на хосте, используем контейнер {container}")
        return [
            "docker", "exec", "-i",
            "-e", f"PGPASSWORD={pgpassword}",
            container,
        ], True

    raise RuntimeError(
        "ogr2ogr не найден ни на хосте, ни в GeoServer-контейнере. "
        "Установите gdal-bin: sudo apt install gdal-bin"
    )


def import_vectors(gpkg_path: Path):
    """Импортирует слои GPKG в PostGIS (agrifields, razgrafka, assessment).

    Если ogr2ogr не установлен на хосте, использует его из GeoServer-контейнера:
    GPKG копируется во временную папку внутри shared volume (./data/).
    """
    if not gpkg_path.exists():
        raise FileNotFoundError(f"vectors.gpkg не найден: {gpkg_path}")

    # (ogr_prefix и via_docker уже определены выше)

    password = FRONTEND_DB["password"]
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    ogr_prefix, via_docker = _ogr2ogr_cmd(password)

    # В docker-сети PostGIS доступен по имени сервиса, порт всегда 5432.
    # На хосте — через настроенный FRONTEND_DB_HOST/PORT.
    if via_docker:
        db_host = "postgis"
        db_port = "5432"
    else:
        db_host = FRONTEND_DB["host"]
        db_port = str(FRONTEND_DB["port"])

    conn_str = (
        f"PG:dbname={FRONTEND_DB['name']} "
        f"host={db_host} "
        f"port={db_port} "
        f"user={FRONTEND_DB['user']}"
    )

    # При docker exec GPKG должен быть доступен внутри контейнера.
    # GeoServer монтирует ./data → /mnt/data, поэтому копируем туда.
    if via_docker:
        tmp_gpkg_host = GEODATA_DIR.parent / "_tmp_vectors.gpkg"
        shutil.copy(gpkg_path, tmp_gpkg_host)   # copy, not copy2: copystat fails on some mounts
        gpkg_in_container = "/mnt/data/_tmp_vectors.gpkg"
    else:
        gpkg_in_container = str(gpkg_path)

    # (layer_name, has_geometry)
    layers = [
        ("agrifields", True),
        ("razgrafka",  True),
        ("assessment", False),
    ]

    try:
        for layer, has_geom in layers:
            logger.info(f"  Импортирую слой: {layer}")
            cmd = ogr_prefix + [
                "ogr2ogr",
                "-f", "PostgreSQL",
                conn_str,
                gpkg_in_container,
                layer,
                "-nln", layer,
                "-overwrite",
            ]
            if has_geom:
                cmd += ["-lco", "GEOMETRY_NAME=geom"]

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.error(f"Ошибка импорта '{layer}':\n{result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)
    finally:
        if via_docker and tmp_gpkg_host.exists():
            tmp_gpkg_host.unlink()

    logger.info("Векторные данные импортированы.")


def recreate_views(sql_path: Path):
    """Выполняет SQL-скрипт из пакета для пересоздания view assessment_ready."""
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL-скрипт не найден в пакете: {sql_path}")

    env = os.environ.copy()
    env["PGPASSWORD"] = FRONTEND_DB["password"]

    cmd = [
        "psql",
        "-h", FRONTEND_DB["host"],
        "-p", str(FRONTEND_DB["port"]),
        "-U", FRONTEND_DB["user"],
        "-d", FRONTEND_DB["name"],
        "-f", str(sql_path),
        "-v", "ON_ERROR_STOP=1",
    ]

    logger.info("Пересоздаю view assessment_ready...")
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка выполнения SQL-скрипта:\n{e.stderr}")
        raise

    logger.info("View пересоздан.")


def _reload_one_store(store_name: str, year: int, auth: tuple):
    """Обновляет один ImageMosaic-стор: URL → reset → nativeCoverageName."""
    base = (
        f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
        f"/coveragestores/{store_name}"
    )

    # 1. Обновить URL хранилища
    resp = requests.put(
        f"{base}.json", auth=auth,
        json={"coverageStore": {"url": f"file:///mnt/data/geodata/{year}/", "enabled": True}},
        timeout=30,
    )
    if resp.status_code == 200:
        logger.info(f"  [{store_name}] URL → geodata/{year}/")
    else:
        logger.warning(f"  [{store_name}] PUT store вернул {resp.status_code}: {resp.text[:200]}")

    # 2. Сбросить кэш (GeoServer пересканирует директорию)
    resp = requests.post(f"{base}/reset", auth=auth, timeout=30)
    if resp.status_code == 200:
        logger.info(f"  [{store_name}] кэш сброшен")
    else:
        logger.warning(f"  [{store_name}] reset вернул {resp.status_code}: {resp.text[:200]}")

    # 3. Обновить nativeCoverageName (должно совпадать с именем папки / TypeName в *.properties)
    resp = requests.put(
        f"{base}/coverages/{store_name}.json", auth=auth,
        json={"coverage": {"nativeCoverageName": str(year)}},
        timeout=30,
    )
    if resp.status_code == 200:
        logger.info(f"  [{store_name}] nativeCoverageName → {year}")
    else:
        logger.warning(f"  [{store_name}] PUT coverage вернул {resp.status_code}: {resp.text[:200]}")


def reload_geoserver(rasters_by_year: dict):
    """Обновляет ImageMosaic-сторы для всех доставленных годов.

    Логика именования сторов:
    - последний год  → GEOSERVER_COVERAGESTORE          (напр. "image_assessment")
    - прочие годы   → GEOSERVER_COVERAGESTORE_{year}    (напр. "image_assessment_2024")
    """
    years_with_data = {y: c for y, c in rasters_by_year.items() if c > 0}
    if not years_with_data:
        logger.info("TIF не копировались — перезагрузка GeoServer пропущена.")
        return

    auth = (GEOSERVER_USER, GEOSERVER_PASSWORD)

    # Перезагружаем конфигурацию GeoServer — необходимо если конфиги (geoserver_data/)
    # были обновлены на диске, но GeoServer ещё не подхватил их (не перезапускался).
    resp = requests.post(f"{GEOSERVER_URL}/rest/reload", auth=auth, timeout=30)
    if resp.status_code == 200:
        logger.info("GeoServer конфиг перезагружен.")
    else:
        logger.warning(f"GeoServer reload вернул {resp.status_code}")

    latest_year = max(years_with_data.keys())

    for year in sorted(years_with_data.keys()):
        store_name = (
            GEOSERVER_COVERAGESTORE
            if year == latest_year
            else f"{GEOSERVER_COVERAGESTORE}_{year}"
        )
        logger.info(f"Обновляю GeoServer стор '{store_name}' для года {year}...")
        _reload_one_store(store_name, year, auth)


# ---------------------------------------------------------------------------
# Основной процесс
# ---------------------------------------------------------------------------

def deliver(zip_path: Path):
    with tempfile.TemporaryDirectory(prefix="pikurr_deliver_") as tmpdir:
        tmp = Path(tmpdir)

        # 1. Распаковка
        manifest = unpack(zip_path, tmp)
        year = manifest["year"]  # последний год (для legacy-совместимости)

        # 2. Растры (все годы из пакета)
        rasters_by_year = copy_rasters(tmp / "rasters")

        # Legacy-пакет: TIF лежат прямо в rasters/ без подпапок
        if not rasters_by_year:
            tifs = list((tmp / "rasters").glob("*.tif")) + list((tmp / "rasters").glob("*.TIF"))
            if tifs:
                dst = GEODATA_DIR / str(year)
                dst.mkdir(parents=True, exist_ok=True)
                for tif in tifs:
                    shutil.copy2(tif, dst / tif.name)
                rasters_by_year = {year: len(tifs)}
                logger.info(f"Legacy: скопировано {len(tifs)} TIF → {dst}")

        # 3. Векторы → PostGIS
        import_vectors(tmp / "vectors.gpkg")

        # 4. Пересоздать view (SQL-скрипт из самого пакета)
        recreate_views(tmp / "create_assessment_schema.sql")

        # 5. GeoServer reload (все годы)
        reload_geoserver(rasters_by_year)

    # Всё прошло успешно — удаляем пакет
    try:
        zip_path.unlink()
        logger.info(f"Пакет удалён: {zip_path.name}")
    except PermissionError:
        logger.warning(f"Нет прав на удаление пакета: {zip_path} (удалите вручную)")

    logger.info("=== Доставка завершена успешно ===")


def main():
    parser = argparse.ArgumentParser(description="Доставка пакета обновлений PIKURR")
    parser.add_argument(
        "zip_path",
        nargs="?",
        type=Path,
        help="Путь к ZIP-пакету. По умолчанию — последний в outputs/dist/",
    )
    args = parser.parse_args()

    zip_path = args.zip_path or find_latest_zip(DEFAULT_DIST_DIR)
    logger.info(f"Пакет: {zip_path}")

    if not zip_path.exists():
        logger.error(f"Файл не найден: {zip_path}")
        sys.exit(1)

    deliver(zip_path)


if __name__ == "__main__":
    main()
