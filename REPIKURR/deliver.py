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
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Конфигурация (переопределяется через переменные окружения)
# ---------------------------------------------------------------------------

def _required_env(name: str) -> str:
    """round21, B1: пароли раньше имели дефолты ("pikurr", "geoserver"),
    закоммиченные в публичный репозиторий вместе с этим файлом — на VPS с
    доменом это открытая админка GeoServer с известным паролем. Без значения
    падаем сразу и внятно, а не продолжаем с дефолтом."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Переменная окружения {name} не задана (и не имеет дефолта — "
            f"round21, B1). См. deliver.env.example."
        )
    return value


FRONTEND_DB = {
    "host": os.getenv("FRONTEND_DB_HOST", "localhost"),
    "port": int(os.getenv("FRONTEND_DB_PORT", "5433")),
    "user": os.getenv("FRONTEND_DB_USER", "pikurr"),
    "password": _required_env("FRONTEND_DB_PASSWORD"),
    "name": os.getenv("FRONTEND_DB_NAME", "pikurr"),
}

# round26, B1: порог допустимой усадки _stage относительно боевой таблицы
# (доля, 0.10 = 10%). Выбран как «на порядок больше обычной вариации
# между доставками» (в наблюдавшихся прогонах round25/round26 изменения
# между доставками — единицы объектов на ~59000, то есть доли процента),
# но заметно меньше катастрофической потери (пустой или наполовину
# урезанный слой) — так порог ловит именно битые/неполные пакеты, не
# нормальные правки полей. Обосновано, не взято произвольно; при
# необходимости легитимной массовой правки — флаг --allow-shrink.
DEFAULT_SHRINK_THRESHOLD = 0.10

GEOSERVER_URL = os.getenv("GEOSERVER_URL", "http://localhost:8090/geoserver")
GEOSERVER_USER = os.getenv("GEOSERVER_USER", "admin")
GEOSERVER_PASSWORD = _required_env("GEOSERVER_PASSWORD")
GEOSERVER_WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "pikurr")
GEOSERVER_COVERAGESTORE = os.getenv("GEOSERVER_COVERAGESTORE", "image_assessment")

SCRIPT_DIR = Path(__file__).resolve().parent
GEODATA_DIR = SCRIPT_DIR / "data" / "geodata"
STATUS_DIR = SCRIPT_DIR / "status"
# round23, задача 1: статика для списка годов/районов — отдаётся Caddy,
# не GeoServer (см. write_year_district_lookup()).
STATIC_DIR = SCRIPT_DIR / "static"

# pikurr_update_{years_tag}_{YYYY-MM-DD_HH-MM}.zip — years_tag сам может
# содержать подчёркивания, поэтому имя разбирается по дате в конце, а не
# лексикографически (см. round19: лексикографическая сортировка ломается
# при изменении длины years_tag между прогонами).
_PACKAGE_DATE_RE = re.compile(r'^pikurr_update_.+_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.zip$')

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

def _package_sort_key(path: Path) -> datetime:
    match = _PACKAGE_DATE_RE.match(path.name)
    if not match:
        raise ValueError(f"Не удалось разобрать дату из имени пакета: {path.name}")
    return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M")


def find_latest_zip(dist_dir: Path) -> Path:
    zips = list(dist_dir.glob("pikurr_update_*.zip"))
    if not zips:
        raise FileNotFoundError(f"Нет ZIP-пакетов в {dist_dir}")
    return max(zips, key=_package_sort_key)


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


def _clear_stale_rasters(dst: Path, keep_names: set, year: int):
    """Убирает из dst TIF, отсутствующих в новом пакете.

    Пакет содержит год целиком, поэтому лист, которого нет в новом пакете,
    выведен из состава — его старый TIF в data/geodata/ иначе остаётся
    навсегда (round19: 1048 файлов на диске при 912 в пакете). Не удаляет —
    переносит в _removed_{дата}/{year}/, чтобы состав можно было осмотреть
    (round20, задача 2: "перед удалением чего-либо" — здесь удаления вообще
    нет, только перенос).
    """
    existing = list(dst.glob("*.tif")) + list(dst.glob("*.TIF"))
    stale = [p for p in existing if p.name not in keep_names]
    if not stale:
        return
    logger.info(
        f"Растры {year} года, отсутствующие в новом пакете ({len(stale)}): "
        f"{sorted(p.name for p in stale)}"
    )
    removed_dir = GEODATA_DIR / f"_removed_{datetime.now():%Y%m%d_%H%M%S}" / str(year)
    removed_dir.mkdir(parents=True, exist_ok=True)
    for p in stale:
        p.rename(removed_dir / p.name)
    logger.info(f"Перенесено {len(stale)} устаревших растров ({year}) → {removed_dir}")


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
            _clear_stale_rasters(dst, {t.name for t in tifs}, year)
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
    """Возвращает (prefix, via_docker). prefix уже включает сам "ogr2ogr" —
    вызывающий код не должен добавлять его повторно (round22: латентный баг —
    вызывающий код делал `ogr_prefix + ["ogr2ogr", ...]`, из-за чего при
    host-варианте команда превращалась в `ogr2ogr ogr2ogr -f ...` — GDAL
    трактовал второй "ogr2ogr" как имя ВЫХОДНОГО датасета и пытался создать
    БД с таким именем, откуда и загадочная ошибка "driver doesn't currently
    support database creation". Раньше это не проявлялось, так как на
    192.168.251.190 ogr2ogr на хосте никогда не было — всегда шло через
    docker exec, где дублирования не было; проявилось только когда ogr2ogr
    поставили прямо на хост VPS).

    via_docker=False: ['ogr2ogr'] — запуск на хосте, пароль через env.
    via_docker=True:  ['docker','exec',...,'ogr2ogr'] — запуск в
                      GeoServer-контейнере, пароль передаётся через -e PGPASSWORD.
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
            container, "ogr2ogr",
        ], True

    raise RuntimeError(
        "ogr2ogr не найден ни на хосте, ни в GeoServer-контейнере. "
        "Установите gdal-bin: sudo apt install gdal-bin"
    )


class SwapGuardError(RuntimeError):
    """round26, B1: _stage пуст или меньше боевой таблицы больше порога."""
    pass


class SchemaVersionError(RuntimeError):
    """round29, блок A: пакет несёт SQL-схему СТАРШЕ, чем уже применённая
    на боевой БД — доставка отклоняется до единого изменения БД, чтобы
    не откатить схему назад (найдено фактом: рассинхрон стенда с
    репозиторием мог унести на VPS устаревший SQL, round29 A1-A2)."""
    pass


_SCHEMA_VERSION_MARKER_RE = re.compile(r'--\s*SCHEMA_VERSION\s*=\s*(\d+)')


def _package_schema_version(sql_path: Path) -> int | None:
    """round29, блок A: версия схемы, заявленная пакетом (маркер
    `-- SCHEMA_VERSION = N` в начале create_assessment_schema.sql).
    None — в пакете нет этого файла (легаси/assessment-only пакет,
    не трогающий схему — не о чем предупреждать) или маркер не найден."""
    if not sql_path.exists():
        return None
    text = sql_path.read_text(encoding="utf-8")
    m = _SCHEMA_VERSION_MARKER_RE.search(text)
    return int(m.group(1)) if m else None


def import_vectors(gpkg_path: Path, *, staged: bool = True,
                    shrink_threshold: float = DEFAULT_SHRINK_THRESHOLD,
                    allow_shrink: bool = False):
    """Импортирует слои GPKG в PostGIS (agrifields, razgrafka, assessment).

    round25, блок B2: по умолчанию (`staged=True`) ogr2ogr пишет во
    временные таблицы `<layer>_stage`, а не в боевые — `-overwrite`
    внутри ogr2ogr делает `DROP TABLE ... CASCADE` для того имени,
    которое ему передано (round24, задача 2: это подтверждённый факт,
    не догадка), и раньше это имя было именем боевой таблицы
    `agrifields`, от которой зависит `assessment_ready`. DROP боевой
    таблицы каскадом ронял представление на каждой доставке. Перенос
    из стейджинга в боевые таблицы — отдельным шагом, см.
    `_swap_staged_tables()`.

    `staged=False` — старое поведение (импорт прямо в боевые имена);
    оставлено для отладки/сравнения, в штатном пайплайне не
    используется.

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

    suffix = "_stage" if staged else ""

    try:
        for layer, has_geom in layers:
            target = f"{layer}{suffix}"
            logger.info(f"  Импортирую слой: {layer} → {target}")
            cmd = ogr_prefix + [
                "-f", "PostgreSQL",
                conn_str,
                gpkg_in_container,
                layer,
                "-nln", target,
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

    if staged:
        logger.info("Векторные данные импортированы во временные таблицы (_stage).")
        _swap_staged_tables(
            [layer for layer, _ in layers],
            shrink_threshold=shrink_threshold,
            allow_shrink=allow_shrink,
        )
    else:
        logger.info("Векторные данные импортированы (без staging).")


_SWAP_ABORT_RE = re.compile(r"SWAP_ABORT\|([^|]+)\|([^|]+)\|stage=(\d+)\|prod=(\d+)")


def _table_exists(table: str) -> bool:
    """round28, блок E: проверка перед тем, как что-то делать с боевой
    таблицей — на самой первой доставке (пустая БД) её ещё нет."""
    return _run_psql(f"SELECT to_regclass('{table}') IS NOT NULL;").strip() == "t"


def _stage_columns(layer: str) -> list[str]:
    """round28, блок E: реальный список колонок '<layer>_stage' (в том
    порядке, в котором их создал ogr2ogr) — основа для явного списка
    колонок в INSERT, устойчивого к лишним колонкам у боевой таблицы
    (например, 'valuation' у assessment, которой ogr2ogr не создаёт)."""
    result = _run_psql(
        f"SELECT string_agg(column_name, ',' ORDER BY ordinal_position) "
        f"FROM information_schema.columns WHERE table_name = '{layer}_stage';"
    ).strip()
    if not result:
        raise RuntimeError(f"Не удалось получить список колонок '{layer}_stage' (таблица пуста или не существует?).")
    return result.split(",")


def _swap_staged_tables(layers: list[str], *,
                         shrink_threshold: float = DEFAULT_SHRINK_THRESHOLD,
                         allow_shrink: bool = False):
    """Переносит данные из `<layer>_stage` в боевые таблицы одной
    транзакцией (`TRUNCATE` + `INSERT ... SELECT`) и удаляет staging-
    таблицы. round25, блок B2.

    `TRUNCATE` не роняет OID боевой таблицы и не требует пересоздания
    зависимых объектов (в отличие от `DROP ... CASCADE`, которым грешит
    `ogr2ogr -overwrite`) — `assessment_ready` (материализованное
    представление над `agrifields`/`assessment`) переживает эту
    операцию, продолжая отдавать СТАРЫЕ, ещё валидные данные вплоть до
    следующего `REFRESH MATERIALIZED VIEW`. Именно так достигается
    отсутствие окна недоступности WFS/WMS во время доставки.

    round26, B1: битый/усечённый пакет раньше проходил бы этот перенос
    без единой проверки — TRUNCATE+INSERT отработали бы, REFRESH прошёл
    бы, статус был бы `ok: true`, а витрина осталась бы с пустыми/
    урезанными боевыми данными. Перед TRUNCATE каждого слоя, ВНУТРИ той
    же транзакции, сверяем число строк `_stage` с текущим числом строк
    боевой таблицы: если `_stage` пуст, или меньше боевой больше чем на
    `shrink_threshold` — транзакция откатывается целиком (RAISE
    EXCEPTION внутри BEGIN/COMMIT), боевые таблицы не тронуты.
    `allow_shrink=True` (флаг `--allow-shrink`) отключает обе проверки —
    для законного случая, когда данных должно стать меньше.

    round28, блок E: если боевая таблица ещё не существует вообще
    (самая первая доставка на пустую БД — найдено фактом при
    развёртывании эмулятора с нуля, round27/28) — раньше проверка
    объёма падала с ошибкой Postgres «relation does not exist» вместо
    внятного пути. Теперь для таких слоёв: guard по объёму пропускается
    (сравнивать не с чем), а сама боевая таблица создаётся по образцу
    `_stage` (`CREATE TABLE ... LIKE ... INCLUDING ALL`) внутри той же
    транзакции — атомарно с переносом данных.

    round28, блок E: `INSERT INTO {layer} SELECT * FROM {layer}_stage`
    (позиционный, без списка колонок) предполагал одинаковый набор/
    порядок колонок в боевой и `_stage` таблице — не так для
    `assessment`, где боевая таблица содержит дополнительную колонку
    `valuation` (заполняется отдельно от импорта, отсутствует у
    `ogr2ogr`). INSERT теперь использует явный список колонок `_stage`
    (устойчиво к любым лишним колонкам цели, не только к `valuation`).
    """
    existing = {layer: _table_exists(layer) for layer in layers}
    missing = [layer for layer, exists in existing.items() if not exists]
    for layer in missing:
        logger.warning(
            f"  Боевая таблица '{layer}' не существует — похоже, это первая "
            f"доставка. Создаю по образцу '{layer}_stage'."
        )

    statements = []
    if not allow_shrink:
        for layer in layers:
            if layer in missing:
                continue  # нечего сравнивать — таблицы ещё нет
            statements.append(f"""
DO $$
DECLARE
  stage_count bigint;
  prod_count bigint;
BEGIN
  SELECT count(*) INTO stage_count FROM {layer}_stage;
  SELECT count(*) INTO prod_count FROM {layer};
  IF stage_count = 0 THEN
    RAISE EXCEPTION 'SWAP_ABORT|{layer}|stage_empty|stage=%|prod=%', stage_count, prod_count;
  ELSIF prod_count > 0 AND stage_count < prod_count * {1 - shrink_threshold} THEN
    RAISE EXCEPTION 'SWAP_ABORT|{layer}|shrink_over_threshold|stage=%|prod=%', stage_count, prod_count;
  END IF;
END $$;
""".strip())

    for layer in missing:
        statements.append(f"CREATE TABLE {layer} (LIKE {layer}_stage INCLUDING ALL);")
        # round28, блок E (найдено фактом при проверке с нуля на эмуляторе):
        # "LIKE ... INCLUDING ALL" копирует DEFAULT-выражение колонок
        # дословно — для SERIAL-колонки (например, ogr2ogr'овский
        # "ogc_fid") это буквально nextval('{layer}_stage_ogc_fid_seq'),
        # т.е. боевая таблица остаётся привязана к ПОСЛЕДОВАТЕЛЬНОСТИ
        # _stage-таблицы. Ниже DROP TABLE {layer}_stage тогда падает:
        # "cannot drop table ... because other objects depend on it".
        # Перепривязываем такие колонки на свежую, "родную" для боевой
        # таблицы последовательность — до TRUNCATE/INSERT, тем же BEGIN.
        statements.append(f"""
DO $$
DECLARE
  col RECORD;
  newseq TEXT;
BEGIN
  FOR col IN
    SELECT a.attname
    FROM pg_attrdef d
    JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
    WHERE d.adrelid = '{layer}'::regclass
      AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%{layer}_stage%'
  LOOP
    newseq := '{layer}_' || col.attname || '_seq';
    EXECUTE format('CREATE SEQUENCE %I OWNED BY %I.%I', newseq, '{layer}', col.attname);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT nextval(%L)', '{layer}', col.attname, newseq);
  END LOOP;
END $$;
""".strip())

    truncate_list = ", ".join(layers)
    statements.append(f"TRUNCATE {truncate_list};")
    for layer in layers:
        cols = _stage_columns(layer)
        col_list = ", ".join(cols)
        statements.append(f"INSERT INTO {layer} ({col_list}) SELECT {col_list} FROM {layer}_stage;")
    for layer in layers:
        statements.append(f"DROP TABLE {layer}_stage;")
    sql = "BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;\n"

    env = os.environ.copy()
    env["PGPASSWORD"] = FRONTEND_DB["password"]
    cmd = [
        "psql",
        "-h", FRONTEND_DB["host"],
        "-p", str(FRONTEND_DB["port"]),
        "-U", FRONTEND_DB["user"],
        "-d", FRONTEND_DB["name"],
        "-v", "ON_ERROR_STOP=1",
    ]
    logger.info("Переношу данные из _stage в боевые таблицы (одна транзакция)...")
    result = subprocess.run(cmd, input=sql, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        abort_match = _SWAP_ABORT_RE.search(result.stderr)
        if abort_match:
            layer, reason, stage_n, prod_n = abort_match.groups()
            reason_ru = {
                "stage_empty": "_stage пуст",
                "shrink_over_threshold": f"_stage меньше боевой более чем на "
                                          f"{shrink_threshold:.0%} (порог)",
            }.get(reason, reason)
            message = (
                f"Перенос из _stage отменён (round26, B1): слой '{layer}' — "
                f"{reason_ru}. _stage={stage_n} строк, боевая={prod_n} строк. "
                f"Боевые таблицы НЕ тронуты (транзакция откачена). "
                f"Если это ожидаемо — перезапустите с --allow-shrink."
            )
            logger.error(message)
            raise SwapGuardError(message)
        logger.error(f"Ошибка переноса из _stage:\n{result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)
    logger.info("Боевые таблицы обновлены, OID сохранён (без DROP CASCADE).")


def ensure_unique_constraint():
    """Гарантирует UNIQUE(fid_ext, year) на assessment, если оно ещё не применено.

    ogr2ogr -overwrite создаёт таблицу assessment собственной схемой раньше,
    чем выполняется create_assessment_schema.sql; CREATE TABLE IF NOT EXISTS
    в нём тогда пропускает создание, и объявленное там ограничение
    (assessment_fid_year_key) никогда фактически не применяется (round19).
    Добавляем его здесь явно, идемпотентно, и без принудительного применения
    при наличии конфликтующих строк.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = FRONTEND_DB["password"]
    psql_base = [
        "psql",
        "-h", FRONTEND_DB["host"],
        "-p", str(FRONTEND_DB["port"]),
        "-U", FRONTEND_DB["user"],
        "-d", FRONTEND_DB["name"],
        "-tA",
    ]

    def run_sql(sql: str) -> str:
        result = subprocess.run(psql_base + ["-c", sql], env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Ошибка SQL-запроса ({sql!r}):\n{result.stderr}")
        return result.stdout.strip()

    exists = run_sql(
        "SELECT 1 FROM pg_constraint WHERE conname = 'assessment_fid_year_key';"
    )
    if exists == "1":
        logger.info("Ограничение assessment_fid_year_key уже применено.")
        return

    dup_count = run_sql(
        "SELECT count(*) FROM (SELECT fid_ext, year FROM assessment "
        "GROUP BY fid_ext, year HAVING count(*) > 1) d;"
    )
    if dup_count != "0":
        logger.error(
            f"Ограничение UNIQUE(fid_ext, year) НЕ применено: "
            f"{dup_count} конфликтующих пар (fid_ext, year) в assessment. "
            f"Данные не менялись — конфликт нужно разобрать вручную."
        )
        return

    run_sql("ALTER TABLE assessment ADD CONSTRAINT assessment_fid_year_key UNIQUE (fid_ext, year);")
    logger.info("Ограничение assessment_fid_year_key применено.")


# round27, A2: версия схемы объектов assessment_ready/levelsagg_ready,
# должна совпадать со SCHEMA_VERSION в create_assessment_schema.sql
# (COMMENT ON MATERIALIZED VIEW ... IS 'schema_version=N').
SCHEMA_VERSION = 2
_VERSIONED_MATERIALIZED_VIEWS = ("assessment_ready", "levelsagg_ready")


def _relkind(view_name: str) -> str:
    return _run_psql(
        f"SELECT relkind FROM pg_class WHERE relname = '{view_name}';"
    ).strip()


def _schema_version_on_object(view_name: str) -> int | None:
    """round27, A2: версия схемы, записанная COMMENT ON MATERIALIZED
    VIEW. None — объект не существует или комментарий не задан."""
    comment = _run_psql(
        f"SELECT obj_description('{view_name}'::regclass::oid, 'pg_class');"
    ).strip()
    m = re.search(r"schema_version=(\d+)", comment)
    return int(m.group(1)) if m else None


def assessment_schema_up_to_date() -> bool:
    """round25, блок B2 + round27, блок A2: True, если ВСЕ объекты из
    _VERSIONED_MATERIALIZED_VIEWS уже материализованы (relkind='m') И их
    версия схемы совпадает с SCHEMA_VERSION — тогда recreate_views() не
    нужен, обновление сводится к REFRESH. round26, B5 нашёл фактом:
    `CREATE MATERIALIZED VIEW IF NOT EXISTS` молча пропускает смену
    определения уже существующего объекта — простой relkind='m' (как
    было до этого раунда) не отличает «актуальная схема» от «схема
    старой версии, но уже материализована»; версия на объекте отличает."""
    for view in _VERSIONED_MATERIALIZED_VIEWS:
        try:
            if _relkind(view) != "m":
                return False
        except RuntimeError:
            return False
        if _schema_version_on_object(view) != SCHEMA_VERSION:
            return False
    return True


def ensure_assessment_schema(sql_path: Path):
    """round27, A2: если версия схемы расходится (или объект отсутствует/
    не материализован) — явно дропает старые материализованные объекты
    ПЕРЕД повторным запуском SQL-скрипта (`CREATE ... IF NOT EXISTS` сам
    по себе не заменит уже существующий объект, round26 B5 — простое
    повторение recreate_views() без явного DROP не решает проблему).
    Если версия совпадает — ничего не делает, OID объектов не меняется."""
    if assessment_schema_up_to_date():
        logger.info(
            f"Схема (schema_version={SCHEMA_VERSION}) актуальна — "
            f"recreate_views пропущен, обновление только через REFRESH."
        )
        return
    logger.info(
        f"Версия схемы объекта не совпадает с SCHEMA_VERSION={SCHEMA_VERSION} "
        f"(или объект отсутствует/не материализован) — пересоздаю."
    )
    for view in _VERSIONED_MATERIALIZED_VIEWS:
        # round28, блок E (найдено фактом при проверке с нуля на эмуляторе):
        # после bootstrap-заглушки объект — обычный VIEW, не
        # MATERIALIZED VIEW; "DROP MATERIALIZED VIEW IF EXISTS" в этом
        # случае падает ("... is not a materialized view"), т.к. IF
        # EXISTS проверяет только наличие ИМЕНИ, не тип объекта. Дропаем
        # оба варианта — ровно как уже делает bootstrap_empty_schema.sql
        # для этого же перехода "было VIEW → стало MATERIALIZED VIEW".
        _run_psql(f"DROP VIEW IF EXISTS {view} CASCADE;")
        _run_psql(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;")
    recreate_views(sql_path)


def recreate_views(sql_path: Path):
    """Выполняет SQL-скрипт из пакета для пересоздания view assessment_ready.

    round25, блок B2: теперь это путь МИГРАЦИИ (первое развёртывание —
    объекта ещё нет, либо объект существует, но не того типа — например,
    обычный VIEW от заглушки), а не шаг каждой доставки. На каждой
    доставке, где assessment_ready уже материализован, этот шаг
    пропускается вызывающим кодом (`deliver()`), и обновление сводится
    к единственному `REFRESH MATERIALIZED VIEW`."""
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


def _run_psql(sql: str) -> str:
    """Выполняет один SQL-запрос через psql, возвращает stdout (без заголовков/рамок)."""
    env = os.environ.copy()
    env["PGPASSWORD"] = FRONTEND_DB["password"]
    cmd = [
        "psql",
        "-h", FRONTEND_DB["host"],
        "-p", str(FRONTEND_DB["port"]),
        "-U", FRONTEND_DB["user"],
        "-d", FRONTEND_DB["name"],
        "-v", "ON_ERROR_STOP=1",
        "-tA",  # без заголовков/рамок, без padding — удобно парсить
        "-c", sql,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ошибка SQL-запроса ({sql!r}):\n{result.stderr}")
    return result.stdout


def refresh_materialized_view():
    """REFRESH MATERIALIZED VIEW assessment_ready, levelsagg_ready
    (round23, задача 2; levelsagg_ready добавлен round27, A1).

    Обычный REFRESH, не CONCURRENTLY: держит ACCESS EXCLUSIVE лок на время
    пересборки (замер на боевых данных VPS — секунды, не минуты), но не
    требует второй копии данных на диске и самого механизма CONCURRENTLY
    (который сам медленнее обычного REFRESH). На витрине с редкими
    доставками (не чаще нескольких раз в год) и невысоким постоянным
    трафиком короткая блокировка на чтение не обосновывает эту сложность —
    уникальный индекс (nr_user, year)/(usname, usern_co, rn) уже есть в
    схеме, so при необходимости перейти на CONCURRENTLY в будущем — чисто
    техническая правка.

    round27, A1: levelsagg_ready заменил прямое чтение featuretype
    `levelsagg` из боевой agrifields (round26, B2: блокировался на всё
    время транзакции подмены _stage→боевые, ~14.6с на VPS) — обновляется
    здесь же, той же доставкой, что и assessment_ready, ПОСЛЕ подмены
    _stage→боевые (agrifields к этому моменту уже боевая, свежая).
    """
    logger.info("Обновляю материализованные представления assessment_ready, levelsagg_ready...")
    t0 = time.monotonic()
    _run_psql("REFRESH MATERIALIZED VIEW assessment_ready;")
    _run_psql("REFRESH MATERIALIZED VIEW levelsagg_ready;")
    elapsed = time.monotonic() - t0
    logger.info(f"Представления обновлены за {elapsed:.2f}с.")
    return elapsed


def write_year_district_lookup():
    """Пишет static/year_district.json (round23, задача 1).

    Раньше фронтенд (loadYearDistrictData()) получал список годов и
    районов через WFS-запрос ко ВСЕМ 55784+ объектам pikurr:fields — тяжёлая
    передача данных (включая геометрию каждого поля) только чтобы построить
    выпадающие списки. Разведка (round23) подтвердила: используются только
    уникальные годы и районы по году, ничего поэлементного. Данные меняются
    только при доставке — считаем один раз здесь, отдаём статикой через
    Caddy, GeoServer в этом запросе больше не участвует.
    """
    rows = _run_psql(
        "SELECT DISTINCT year, district FROM assessment_ready "
        "WHERE district IS NOT NULL ORDER BY year, district;"
    )
    years: list[int] = []
    districts_by_year: dict[int, list[str]] = {}
    for line in rows.splitlines():
        line = line.strip()
        if not line:
            continue
        year_str, district = line.split("|", 1)
        year = int(year_str)
        if year not in districts_by_year:
            districts_by_year[year] = []
            years.append(year)
        districts_by_year[year].append(district)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"years": sorted(years), "districtsByYear": districts_by_year}
    path = STATIC_DIR / "year_district.json"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False))
    tmp_path.replace(path)  # атомарно
    logger.info(f"Список годов/районов записан: {path} ({len(years)} лет)")


# Файлы персистентного каталога гранул ImageMosaic (не сам .properties —
# он описывает тип/формат стора и не портится содержимым каталога).
_MOSAIC_INDEX_EXTENSIONS = {".shp", ".shx", ".dbf", ".qix", ".prj", ".fix", ".dat"}


def _index_files_for_year(year: int) -> list[Path]:
    year_dir = GEODATA_DIR / str(year)
    if not year_dir.exists():
        return []
    return sorted(
        p for p in year_dir.glob(f"{year}.*")
        if p.suffix.lower() in _MOSAIC_INDEX_EXTENSIONS
    )


def _rebuild_mosaic_index(store_name: str, year: int, auth: tuple):
    """Форсирует пересборку каталога гранул ImageMosaic (round20, задача 1).

    round19 установил: POST .../reset сбрасывает только кэш ридеров, а не
    персистентный шейпфайл-индекс — новые/изменённые файлы никогда не
    попадали в каталог, и WMS отдавал старые данные, хотя все шаги доставки
    отчитывались об успехе.

    Порядок важен (см. ТЗ round20): сначала reset — высвобождает файловые
    хендлы GeoServer на текущий индекс; затем удаляются файлы индекса;
    harvest директории заставляет GeoServer пересканировать её и построить
    каталог с нуля; финальный reset подхватывает новый каталог в рантайме.
    """
    base = (
        f"{GEOSERVER_URL}/rest/workspaces/{GEOSERVER_WORKSPACE}"
        f"/coveragestores/{store_name}"
    )

    resp = requests.post(f"{base}/reset", auth=auth, timeout=30)
    if resp.status_code != 200:
        logger.warning(f"  [{store_name}] предварительный reset вернул {resp.status_code}: {resp.text[:200]}")

    removed = []
    for f in _index_files_for_year(year):
        try:
            f.unlink()
            removed.append(f.name)
        except OSError as e:
            logger.warning(f"  [{store_name}] не удалось удалить файл индекса {f}: {e}")
    logger.info(f"  [{store_name}] удалены файлы индекса года {year} ({len(removed)}): {removed}")

    harvest_url = f"{base}/external.imagemosaic"
    directory_uri = f"file:///mnt/data/geodata/{year}/"
    try:
        resp = requests.post(
            harvest_url, auth=auth, data=directory_uri,
            headers={"Content-type": "text/plain"}, timeout=180,
        )
        if resp.status_code in (200, 201, 202):
            logger.info(f"  [{store_name}] harvest каталога {directory_uri}: {resp.status_code}")
        else:
            logger.warning(f"  [{store_name}] harvest вернул {resp.status_code}: {resp.text[:300]}")
    except requests.RequestException as e:
        logger.warning(f"  [{store_name}] harvest не выполнен: {e}")

    resp = requests.post(f"{base}/reset", auth=auth, timeout=30)
    if resp.status_code == 200:
        logger.info(f"  [{store_name}] финальный reset выполнен")
    else:
        logger.warning(f"  [{store_name}] финальный reset вернул {resp.status_code}: {resp.text[:200]}")


def _truncate_gwc_layer_if_cached(store_name: str, auth: tuple):
    """Чистит тайловый кэш GWC для слоя, если он там зарегистрирован (round21,
    A2). Пересборка каталога гранул ImageMosaic (_rebuild_mosaic_index) никак
    не затрагивает GeoWebCache: если для слоя когда-нибудь включат тайловое
    кэширование (сейчас, по проверке на сервере, GWC не кэширует ни один
    слой — но это можно включить через админку без изменений в deliver.py),
    GWC продолжит отдавать старые тайлы даже после успешной пересборки
    индекса — тот же класс отказа, что был с самим индексом (round19).
    """
    layer_name = f"{GEOSERVER_WORKSPACE}:{store_name}"
    check_url = f"{GEOSERVER_URL}/gwc/rest/layers/{layer_name}.xml"
    try:
        resp = requests.get(check_url, auth=auth, timeout=15)
    except requests.RequestException as e:
        logger.warning(f"  [{store_name}] проверка GWC не выполнена: {e}")
        return

    if resp.status_code != 200:
        logger.info(f"  [{store_name}] слой не зарегистрирован в GWC ({resp.status_code}) — очистка тайлового кэша не нужна")
        return

    logger.info(f"  [{store_name}] слой кэшируется в GWC — очищаю тайловый кэш (masstruncate)")
    body = f"<truncateLayer><layerName>{layer_name}</layerName></truncateLayer>"
    try:
        resp = requests.post(
            f"{GEOSERVER_URL}/gwc/rest/masstruncate", auth=auth,
            data=body, headers={"Content-type": "text/xml"}, timeout=60,
        )
        if resp.status_code in (200, 201, 202):
            logger.info(f"  [{store_name}] тайловый кэш GWC очищен")
        else:
            logger.warning(f"  [{store_name}] masstruncate вернул {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        logger.warning(f"  [{store_name}] masstruncate не выполнен: {e}")


def _reload_one_store(store_name: str, year: int, auth: tuple):
    """Обновляет один ImageMosaic-стор: URL → пересборка индекса → очистка GWC → nativeCoverageName."""
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

    # 2. Пересобрать каталог гранул (round20, задача 1) — раньше здесь был
    # просто /reset, который не решал проблему (round19).
    _rebuild_mosaic_index(store_name, year, auth)

    # 2б. Тайловый кэш GWC — отдельный слой кэширования, индексация мозаики
    # его не трогает (round21, A2).
    _truncate_gwc_layer_if_cached(store_name, auth)

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


def count_granules_in_index(year: int) -> int | None:
    """Считает число гранул в каталоге мозаики для года.

    round21, задача A3: раньше здесь был `docker exec ... ogrinfo` — членство
    в группе docker равносильно root на хосте, несовместимо с
    непривилегированным пользователем доставки, который планируется для VPS
    (часть B). geoserver_data смонтирован с хоста, поэтому .dbf читается
    напрямую средствами Python, без контейнера.

    Формат dBASE (III+): число записей — little-endian uint32 в байтах 4-7
    заголовка файла. Текущая реализация индекса — шейпфайл (2025.shp/.dbf),
    см. round19. Возвращает None, если посчитать не удалось (не считается
    ошибкой сама по себе — статус доставки просто не будет содержать эту
    величину).
    """
    dbf_path = GEODATA_DIR / str(year) / f"{year}.dbf"
    if not dbf_path.exists():
        logger.warning(f"Индекс не найден: {dbf_path}")
        return None
    try:
        with open(dbf_path, "rb") as f:
            header = f.read(8)
    except OSError as e:
        logger.warning(f"Не удалось прочитать индекс {dbf_path}: {e}")
        return None
    if len(header) < 8:
        logger.warning(f"Индекс повреждён или пуст: {dbf_path}")
        return None
    return struct.unpack("<I", header[4:8])[0]


def reload_geoserver(rasters_by_year: dict) -> int | None:
    """Обновляет ImageMosaic-сторы для всех доставленных годов.

    Логика именования сторов:
    - последний год  → GEOSERVER_COVERAGESTORE          (напр. "image_assessment")
    - прочие годы   → GEOSERVER_COVERAGESTORE_{year}    (напр. "image_assessment_2024")

    Возвращает число гранул в индексе последнего года после обработки —
    это НЕ подтверждение, что переиндексация действительно произошла
    (см. round19: /reset сбрасывает только кэш ридеров, не каталог гранул),
    а честный факт: сколько гранул в индексе сейчас. Используется как
    granules_after в статусе доставки, чтобы несоответствие с числом
    скопированных TIF было видно сразу, а не через пять месяцев.
    """
    years_with_data = {y: c for y, c in rasters_by_year.items() if c > 0}
    if not years_with_data:
        logger.info("TIF не копировались — перезагрузка GeoServer пропущена.")
        return None

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

    expected = years_with_data.get(latest_year)
    granules_after = _wait_for_granule_count(latest_year, expected)
    if granules_after is not None and expected is not None and granules_after != expected:
        logger.warning(
            f"Гранул в индексе {latest_year}: {granules_after}, а доставлено TIF: "
            f"{expected} — расхождение означает, что мозаика не отражает свежие данные."
        )
    return granules_after


def _wait_for_granule_count(year: int, expected: int | None,
                             timeout: float = 180, interval: float = 5) -> int | None:
    """Пересборка индекса на сотнях файлов не мгновенна — опрашиваем каталог,
    а не проверяем один раз сразу после harvest."""
    deadline = time.monotonic() + timeout
    count = count_granules_in_index(year)
    while expected is not None and count != expected and time.monotonic() < deadline:
        time.sleep(interval)
        count = count_granules_in_index(year)
    return count


# ---------------------------------------------------------------------------
# Основной процесс
# ---------------------------------------------------------------------------

class _StepTracker:
    """Держит имя текущего шага, чтобы при исключении (или сигнале —
    round25, блок B4) можно было записать его в статус доставки, не
    оборачивая каждый вызов в свой try/except.

    round25, блок B4: присваивание `tracker.step = "X"` больше не тихое —
    каждая смена шага сразу пишет промежуточный статус-файл
    (`step_in_progress`, `ok: null`), а не только `finally` в конце.
    Раньше `kill -9` посреди доставки не оставлял вообще никакого следа
    в status/ (round24, задача 5); теперь виден хотя бы последний шаг,
    на котором доставка была в момент прерывания — при `SIGKILL` этот
    промежуточный файл — единственное свидетельство, финальный `finally`
    всё равно не выполнится (сигнал не перехватываем, это невозможно
    для SIGKILL в принципе)."""
    def __init__(self, zip_name: str, started_at: datetime):
        self.zip_name = zip_name
        self.started_at = started_at
        self._step = "unpack"
        self._write_intermediate()

    @property
    def step(self):
        return self._step

    @step.setter
    def step(self, value):
        self._step = value
        self._write_intermediate()

    def _write_intermediate(self):
        try:
            STATUS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "zip": self.zip_name,
                "started_at": self.started_at.isoformat(),
                "step_in_progress": self._step,
                "ok": None,
            }
            path = STATUS_DIR / f"{self.zip_name}.json"
            tmp_path = path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp_path.replace(path)
        except OSError as e:
            # Не роняем доставку из-за диагностики — но обязательно логируем.
            logger.warning(f"Не удалось записать промежуточный статус: {e}")


def deliver(zip_path: Path, tracker: "_StepTracker", *,
            shrink_threshold: float = DEFAULT_SHRINK_THRESHOLD,
            allow_shrink: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="pikurr_deliver_") as tmpdir:
        tmp = Path(tmpdir)

        # 1. Распаковка
        tracker.step = "unpack"
        manifest = unpack(zip_path, tmp)
        year = manifest["year"]  # последний год (для legacy-совместимости)

        # 1б. round29, блок A: защита от отката схемы — до ЛЮБОГО изменения
        # БД/растров сверяем версию схемы, которую несёт пакет, со своей
        # SCHEMA_VERSION. Пакет старше боевой схемы — отказ, ничего не
        # тронуто (найдено фактом: рассинхрон стенда с репозиторием мог
        # унести на VPS устаревший SQL — не произошло на практике, round29
        # A1-A2, но защита не должна зависеть от того, повезло ли в этот раз).
        tracker.step = "check_schema_version"
        pkg_schema_version = _package_schema_version(tmp / "create_assessment_schema.sql")
        if pkg_schema_version is not None and pkg_schema_version < SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Пакет несёт SCHEMA_VERSION={pkg_schema_version}, боевая "
                f"схема уже на SCHEMA_VERSION={SCHEMA_VERSION} — доставка "
                f"отклонена, чтобы не откатить схему назад. Ничего не "
                f"тронуто. Обновите стенд (`git pull`, пересоберите ETL-"
                f"образ) и соберите пакет заново."
            )

        # 2. Растры (все годы из пакета)
        tracker.step = "copy_rasters"
        rasters_by_year = copy_rasters(tmp / "rasters")

        # Legacy-пакет: TIF лежат прямо в rasters/ без подпапок
        if not rasters_by_year:
            tifs = list((tmp / "rasters").glob("*.tif")) + list((tmp / "rasters").glob("*.TIF"))
            if tifs:
                dst = GEODATA_DIR / str(year)
                dst.mkdir(parents=True, exist_ok=True)
                _clear_stale_rasters(dst, {t.name for t in tifs}, year)
                for tif in tifs:
                    shutil.copy2(tif, dst / tif.name)
                rasters_by_year = {year: len(tifs)}
                logger.info(f"Legacy: скопировано {len(tifs)} TIF → {dst}")

        # 3. Векторы → PostGIS (round25, блок B2: через staging-таблицы —
        # TRUNCATE+INSERT в боевые вместо DROP CASCADE от ogr2ogr -overwrite,
        # сохраняет OID боевых таблиц и не роняет assessment_ready)
        tracker.step = "import_vectors"
        import_vectors(tmp / "vectors.gpkg", shrink_threshold=shrink_threshold,
                        allow_shrink=allow_shrink)

        # 3б. Ограничение, которое ogr2ogr -overwrite не сохраняет (round19/round20 задача 7)
        tracker.step = "ensure_unique_constraint"
        ensure_unique_constraint()

        # 4. Пересоздать view — ТОЛЬКО путь миграции (round25, блок B2):
        # если assessment_ready уже материализован, DROP/CREATE не нужны
        # вообще, представление обновляется одним REFRESH ниже. Полный
        # recreate_views() выполняется только на первом развёртывании или
        # если объект существует, но не того типа (например, обычный VIEW
        # от bootstrap-заглушки).
        tracker.step = "recreate_views"
        ensure_assessment_schema(tmp / "create_assessment_schema.sql")

        # 4б. Обновить материализованное представление (round23, задача 2) —
        # после импорта векторов, до перезагрузки слоёв GeoServer (порядок
        # важен: GeoServer не должен обращаться к слою в момент обновления).
        tracker.step = "refresh_materialized_view"
        refresh_seconds = refresh_materialized_view()

        # 4в. Статика для списка годов/районов (round23, задача 1) — читает
        # уже обновлённое представление.
        tracker.step = "write_year_district_lookup"
        write_year_district_lookup()

        # 5. GeoServer reload (все годы)
        tracker.step = "reload_geoserver"
        granules_after = reload_geoserver(rasters_by_year)

        # 6. Проверка по содержимому (round25, блок B5) — тот же критерий,
        # что и весь этот раунд: тело ответа, не код. Не падает саму
        # доставку (пакет уже применён к БД/GeoServer) — только пишет
        # результат в статус, чтобы несоответствие было видно сразу, а не
        # через жалобу пользователя сайта.
        tracker.step = "healthcheck"
        healthcheck_result = _run_healthcheck_safe()

    # Всё прошло успешно — удаляем пакет
    tracker.step = "delete_zip"
    try:
        zip_path.unlink()
        logger.info(f"Пакет удалён: {zip_path.name}")
    except PermissionError:
        logger.warning(f"Нет прав на удаление пакета: {zip_path} (удалите вручную)")

    logger.info("=== Доставка завершена успешно ===")
    return {
        "granules_after": granules_after,
        "refresh_seconds": round(refresh_seconds, 2),
        "healthcheck": healthcheck_result,
    }


def _run_healthcheck_safe() -> dict | None:
    """Запускает healthcheck.py и возвращает его результат для статус-файла.
    round25, блок B5. Ошибка самого healthcheck (например, сеть недоступна
    с этого хоста до публичного домена) не должна маскироваться как
    провал доставки — логируется и возвращается как отдельная пометка."""
    try:
        from healthcheck import run_healthcheck
        base_url = "https://" + os.getenv("DOMAIN", "geobotany.of.by")
        result = run_healthcheck(base_url)
        if result["ok"]:
            logger.info("Healthcheck: всё в порядке.")
        else:
            failed = [c["check"] for c in result["checks"] if not c["ok"]]
            logger.error(f"Healthcheck: ЕСТЬ НЕСООТВЕТСТВИЯ: {failed}")
        return result
    except Exception as e:
        logger.warning(f"Healthcheck не удалось выполнить: {e}")
        return {"ok": None, "error": str(e)}


def write_status(zip_name: str, started_at: datetime, finished_at: datetime,
                  ok: bool, step_failed: str | None = None,
                  error: str | None = None, granules_after: int | None = None,
                  refresh_seconds: float | None = None,
                  healthcheck: dict | None = None):
    """Пишет статус доставки, который PushTask опрашивает по ssh (round19: до
    этого отправляющая сторона не знала, дошла ли доставка до конца).
    Пишется всегда — и при успехе, и при падении на любом шаге."""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "zip": zip_name,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "ok": ok,
        "step_failed": step_failed,
        "error": error,
        "granules_after": granules_after,
        # round23, задача 2: сколько добавляет REFRESH MATERIALIZED VIEW —
        # эта стоимость теперь платится один раз на доставку, а не на
        # каждый запрос пользователя, но добавляется к длительности доставки.
        "refresh_seconds": refresh_seconds,
        # round25, блок B5: результат healthcheck.py — проверка по
        # содержимому ответа, не по коду.
        "healthcheck": healthcheck,
    }
    path = STATUS_DIR / f"{zip_name}.json"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp_path.replace(path)  # атомарно — PushTask не должен увидеть частично записанный файл
    logger.info(f"Статус записан: {path}")


_REMOVED_DIR_RE = re.compile(r'^_removed_(\d{8})_(\d{6})$')


def cleanup_old_artifacts(retention_days: int, dry_run: bool = True) -> dict:
    """Убирает служебные каталоги/файлы старше retention_days (round21, A5):
    data/geodata/_removed_*/ (округ2), status/*.json и failed/*.zip (округ3-4).
    Без ограничения растут бесконечно — на VPS с ограниченным диском это
    станет проблемой. dry_run=True (по умолчанию) только печатает список.
    """
    cutoff = datetime.now() - timedelta(days=retention_days)
    to_delete: list[Path] = []

    if GEODATA_DIR.exists():
        for d in GEODATA_DIR.iterdir():
            if not d.is_dir():
                continue
            m = _REMOVED_DIR_RE.match(d.name)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            if ts < cutoff:
                to_delete.append(d)

    failed_dir = SCRIPT_DIR / "failed"
    for directory, pattern in ((STATUS_DIR, "*.json"), (failed_dir, "*.zip")):
        if not directory.exists():
            continue
        for f in directory.glob(pattern):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            if mtime < cutoff:
                to_delete.append(f)

    logger.info(
        f"Retention ({retention_days} дн., cutoff={cutoff:%Y-%m-%d %H:%M}): "
        f"подлежит удалению {len(to_delete)}: {[str(p) for p in to_delete]}"
    )

    if dry_run:
        logger.info("dry-run — ничего не удалено.")
        return {"would_delete": [str(p) for p in to_delete], "deleted": []}

    deleted = []
    for p in to_delete:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            deleted.append(str(p))
        except OSError as e:
            logger.warning(f"Не удалось удалить {p}: {e}")
    logger.info(f"Удалено {len(deleted)} объектов.")
    return {"would_delete": [], "deleted": deleted}


def main():
    parser = argparse.ArgumentParser(description="Доставка пакета обновлений PIKURR")
    parser.add_argument(
        "zip_path",
        nargs="?",
        type=Path,
        help="Путь к ZIP-пакету. По умолчанию — последний в outputs/dist/",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Убрать старые служебные файлы (retention) вместо доставки пакета",
    )
    parser.add_argument(
        "--retention-days", type=int,
        default=int(os.getenv("DELIVERY_RETENTION_DAYS", "30")),
        help="Порог в днях для --cleanup (по умолчанию из DELIVERY_RETENTION_DAYS или 30)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="С --cleanup: только показать, что будет удалено, не удалять",
    )
    parser.add_argument(
        "--shrink-threshold", type=float, default=DEFAULT_SHRINK_THRESHOLD,
        help=(
            "round26, B1: допустимая доля усадки _stage относительно боевой "
            f"таблицы перед отказом от переноса (по умолчанию {DEFAULT_SHRINK_THRESHOLD})"
        ),
    )
    parser.add_argument(
        "--allow-shrink", action="store_true",
        help="round26, B1: отключить проверку усадки _stage (для законной массовой правки)",
    )
    args = parser.parse_args()

    if args.cleanup:
        cleanup_old_artifacts(args.retention_days, dry_run=args.dry_run)
        return

    zip_path = args.zip_path or find_latest_zip(DEFAULT_DIST_DIR)
    logger.info(f"Пакет: {zip_path}")

    if not zip_path.exists():
        logger.error(f"Файл не найден: {zip_path}")
        sys.exit(1)

    started_at = datetime.now()
    tracker = _StepTracker(zip_path.name, started_at)
    ok = False
    error_msg = None
    granules_after = None
    refresh_seconds = None

    # round25, блок B4: SIGTERM/SIGINT (например, watchdog-перезапуск или
    # штатная остановка ВМ по таймеру) — пишем статус С УКАЗАНИЕМ ШАГА до
    # завершения процесса, а не полагаемся только на `finally` (которое
    # тоже сработает для этих двух сигналов через возбуждаемое исключение,
    # но явный обработчик даёт понятное сообщение об ИМЕННО сигнале, а не
    # просто оборванном стеке). SIGKILL (-9) перехватить в принципе
    # невозможно ни этим, ни любым другим способом — если ВМ остановлена
    # жёстко или процесс убит `kill -9`, статус-файл не будет обновлён
    # вообще, `PushTask` увидит это как таймаут без диагностики. Это
    # осознанное, задокументированное ограничение, не недосмотр.
    def _handle_signal(signum, frame):
        # Пишем ошибку в разделяемую переменную и передаём управление
        # обычному `finally` ниже (через sys.exit — SystemExit не ловится
        # `except Exception`, но `finally` всё равно исполнится) —
        # ЕДИНСТВЕННОЕ место, которое реально пишет статус-файл. Раньше
        # здесь был отдельный write_status() — он писал верный шаг, но
        # `finally` тут же перезаписывал файл с error=None, стирая
        # причину (обнаружено на реальном тесте kill -TERM, round25).
        nonlocal error_msg
        sig_name = signal.Signals(signum).name
        error_msg = f"Прервано сигналом {sig_name}"
        logger.error(
            f"Получен сигнал {sig_name} на шаге '{tracker.step}' — "
            f"записываю статус и завершаюсь."
        )
        sys.exit(143 if signum == signal.SIGTERM else 130)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    healthcheck_result = None
    try:
        result = deliver(zip_path, tracker, shrink_threshold=args.shrink_threshold,
                          allow_shrink=args.allow_shrink)
        granules_after = result.get("granules_after")
        refresh_seconds = result.get("refresh_seconds")
        healthcheck_result = result.get("healthcheck")
        ok = True
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Доставка не удалась на шаге '{tracker.step}'")
    finally:
        finished_at = datetime.now()
        write_status(
            zip_path.name, started_at, finished_at, ok,
            step_failed=None if ok else tracker.step,
            error=error_msg, granules_after=granules_after,
            refresh_seconds=refresh_seconds,
            healthcheck=healthcheck_result,
        )

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
