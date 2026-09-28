import datetime
import hashlib
import json
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from src.core.config import settings
from src.services.db import DatabaseService

logger = logging.getLogger(__name__)

class PackageTask:
    def __init__(self):
        self.settings = settings
        self.db = DatabaseService(settings)
        
        # Источники
        self.public_rasters_dir = settings.paths.public_root
        self.view_name = "assessment_ready" # Имя View в БД для экспорта

        # Цель
        self.dist_dir = settings.paths.dist_dir

        # Та же таблица транслитерации, что ExportTask применяет к именам
        # листов при публикации в geoserver_public (round16: без неё
        # check_missing_sheets сравнивал кириллические имена trapeze_serv
        # с латинскими именами файлов и считал отсутствующими вообще все —
        # обнаружено вживую на первом реальном полном прогоне после round13).
        self.trans_tab = str.maketrans({
            'а':'a', 'б':'b', 'в':'v', 'г':'g', 'д':'d','е':'e',
            'ж':'j', 'з':'z', 'и':'i', 'к':'k', 'л':'l', 'м':'m',
            'н':'n', 'о':'o', 'п':'p', 'р':'r', 'с':'s', 'т':'t',
            'у':'u', 'ф':'f', 'х':'h', 'ц':'c', 'ч':'ch', 'ш':'sh',
            'А':'A', 'Б':'B', 'В':'V', 'Г':'G', 'Д':'D','Е':'E',
            'Ж':'J', 'З':'Z', 'И':'I', 'К':'K', 'Л':'L', 'М':'M',
            'Н':'N', 'О':'O', 'П':'P', 'Р':'R', 'С':'S', 'Т':'T',
            'У':'U', 'Ф':'F', 'Х':'H', 'Ц':'C', 'Ч':'CH', 'Ш':'SH'
        })
        
    def get_target_year(self) -> int:
        now = datetime.datetime.now()
        if now.month < 11:
            return now.year - 1
        return now.year

    def export_vectors(self, output_gpkg: Path):
        """Экспорт таблиц из PostGIS в GeoPackage через ogr2ogr.

        Экспортируем исходные таблицы (не view), чтобы на стороне получателя
        можно было пересоздать view и индексы из SQL-скрипта.
        """
        logger.info(f"Exporting vectors to {output_gpkg.name}...")

        env = os.environ.copy()
        env["PGPASSWORD"] = self.settings.db.password
        conn_str = (
            f"PG:dbname={self.settings.db.name} "
            f"host={self.settings.db.host} "
            f"port={self.settings.db.port} "
            f"user={self.settings.db.user}"
        )

        # Таблицы для экспорта: (sql-запрос, имя слоя в GPKG)
        # ВАЖНО: stats экспортируется как TEXT (не JSONB), потому что GDAL < 3.3
        # не умеет читать String(JSON)-колонки из GeoPackage. На фронтенде view
        # кастует обратно: b.stats::jsonb — это корректно для TEXT-поля с JSON.
        layers = [
            ("SELECT * FROM agrifields", "agrifields"),
            ("SELECT * FROM razgrafka", "razgrafka"),
            ("SELECT id, fid_ext, year, stats::text AS stats, description, updated_at FROM assessment", "assessment"),
        ]

        for sql, layer_name in layers:
            logger.info(f"  Exporting layer: {layer_name}")
            cmd = [
                "ogr2ogr",
                "-f", "GPKG",
                str(output_gpkg),
                conn_str,
                "-sql", sql,
                "-nln", layer_name,
                "-update",   # дописывать в существующий файл
                "-overwrite" # перезаписывать слой если уже есть
            ]
            try:
                subprocess.run(cmd, env=env, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Vector export failed for layer '{layer_name}': {e}")
                raise

        logger.info("Vector export successful.")

    def collect_raster_years(self) -> list[int]:
        """Возвращает отсортированный список годов, для которых есть TIF-файлы."""
        if not self.public_rasters_dir.exists():
            return []
        years = []
        for d in sorted(self.public_rasters_dir.iterdir()):
            if d.is_dir() and d.name.isdigit():
                tifs = list(d.glob("*.tif")) + list(d.glob("*.TIF"))
                if tifs:
                    years.append(int(d.name))
        return years

    def check_missing_sheets(self, years: list[int]) -> None:
        """Сверяет TIF-файлы каждого упаковываемого года со списком листов
        проекта и пишет ERROR по отсутствующим — раньше лист, не попавший в
        сборку (например, упавший при склейке, раунд 12 п.4), молча не
        включался в пакет без единого предупреждения.

        ТЗ раунда 13 называет источником списка `razgrafka`, но это
        общенациональная сетка 1:10000 (21280 листов на всю Беларусь) — сверка
        с ней даёт ~20000 «отсутствующих» на каждый прогон, что не сигнал, а
        шум. Реальный список листов проекта — `trapeze_serv` (912 строк), тот
        же источник, что уже использует `SegmentationTask.get_trap_list()`
        (`settings.dbtables.trap`) для отбора листов на сегментацию. Использую
        его — иначе проверка бесполезна."""
        try:
            df = self.db.execute_query(f"SELECT name FROM {settings.dbtables.trap}")
            all_sheets = set(df["name"].tolist())
        except Exception as e:
            logger.error(f"Не удалось получить список листов {settings.dbtables.trap} для проверки полноты пакета: {e}")
            return

        for year in years:
            year_dir = self.public_rasters_dir / str(year)
            present = {p.stem for p in year_dir.glob("*.tif")} | {p.stem for p in year_dir.glob("*.TIF")}
            # ExportTask публикует файлы под транслитерированным именем
            # (self.trans_tab здесь — та же таблица) — сверять нужно
            # транслитерацию, иначе кириллица никогда не совпадёт с латиницей
            # файлов и «отсутствующими» окажутся все листы разом.
            translit_to_original = {s.translate(self.trans_tab): s for s in all_sheets}
            missing_translit = set(translit_to_original) - present
            missing = sorted(translit_to_original[t] for t in missing_translit)
            if missing:
                logger.error(
                    f"Пакет {year}: {len(missing)} листов из {settings.dbtables.trap} отсутствуют "
                    f"среди TIF в {year_dir} и не попадут в поставку: {missing}"
                )

    def _git_commit(self) -> str | None:
        """Коммит ETL-кода на момент сборки — round38, D1: без этого нельзя
        узнать, каким кодом собран конкретный пакет, задним числом.

        round43, блок C: внутри образа `git` не установлен (сознательно —
        не тянуть системную зависимость в runtime-образ ради однократного
        вызова на этапе сборки), поэтому основной путь — переменная
        окружения `ETL_GIT_COMMIT`, запечённая в образ через `ARG`/`ENV`
        в `Dockerfile` на этапе `docker build` (значение приходит снаружи,
        обычно `git rev-parse HEAD` хоста, выполняющего сборку — см.
        `docs/round43-freeze.md`, блок C). Это надёжнее рантайм-вызова
        `git rev-parse` внутри контейнера: коммит фиксируется РОВНО тем,
        что было при сборке образа, и не меняется, даже если хост потом
        уйдёт вперёд по истории, а старый образ продолжит использоваться
        (см. `PackageTask`, вызывается из уже собранного образа
        `pikurr-system-etl-1`, а не из чекаута на голом хосте). Прямой
        вызов `git rev-parse` — резервный путь для локального запуска вне
        контейнера (например, при разработке/отладке на голом хосте, где
        `git` есть и репозиторий рядом)."""
        env_commit = os.environ.get("ETL_GIT_COMMIT")
        if env_commit and env_commit not in ("unknown", ""):
            return env_commit
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[3],
                capture_output=True, text=True, check=True,
            )
            return out.stdout.strip()
        except Exception as e:
            logger.warning(f"Не удалось определить git-коммит ETL-кода: {e}")
            return None

    def _table_row_counts(self) -> dict:
        counts = {}
        for table in ("agrifields", "razgrafka", "assessment"):
            try:
                df = self.db.execute_query(f"SELECT count(*) AS n FROM {table}")
                counts[table] = int(df["n"].iloc[0])
            except Exception as e:
                logger.warning(f"Не удалось посчитать строки {table}: {e}")
                counts[table] = None
        return counts

    def _raster_counts_by_year(self, years: list[int]) -> dict:
        counts = {}
        for year in years:
            year_dir = self.public_rasters_dir / str(year)
            n = len(list(year_dir.glob("*.tif"))) + len(list(year_dir.glob("*.TIF")))
            counts[str(year)] = n
        return counts

    def create_manifest(self, years: list[int], gpkg_path: Path):
        """Создаёт файл описания пакета.

        round38 (блок D1, разбор подмены боевых данных): версия 2.0 несла
        только годы и дату СБОРКИ ZIP — этого недостаточно, чтобы отличить
        свежий прогон ETL от случайно поднятой старой остановленной базы
        (см. docs/round38-data-incident.md). Версия 2.1 добавляет источник
        (хост/имя БД — не пароль), коммит ETL-кода, число строк по каждой
        боевой таблице, число растровых листов по годам и контрольную сумму
        `vectors.gpkg` — простой честный провенанс, не защита сама по себе
        (её даёт предполётная проверка в deliver.py), а материал для неё и
        для ручного разбора при следующем инциденте.
        """
        latest_year = max(years) if years else self.get_target_year()
        with open(gpkg_path, "rb") as f:
            gpkg_sha256 = hashlib.sha256(f.read()).hexdigest()
        manifest = {
            "created_at": datetime.datetime.now().isoformat(),
            "year": latest_year,        # последний год (для совместимости)
            "years": years,             # все годы, включённые в пакет
            "version": "2.1",
            "contents": ["vectors.gpkg", "rasters/"],
            "source_db": {
                "host": self.settings.db.host,
                "name": self.settings.db.name,
            },
            "etl_git_commit": self._git_commit(),
            "row_counts": self._table_row_counts(),
            "raster_counts_by_year": self._raster_counts_by_year(years),
            "vectors_gpkg_sha256": gpkg_sha256,
        }
        return json.dumps(manifest, indent=2)

    def run(self):
        # Определяем доступные годы по папкам с TIF
        raster_years = self.collect_raster_years()
        if not raster_years:
            logger.warning("Не найдено ни одной папки с TIF-файлами. Растры в пакет не войдут.")
        else:
            self.check_missing_sheets(raster_years)
        latest_year = max(raster_years) if raster_years else self.get_target_year()

        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        years_tag = "_".join(str(y) for y in raster_years) if raster_years else str(latest_year)
        package_name = f"pikurr_update_{years_tag}_{date_str}"

        # 1. Подготовка временной папки для сборки
        build_dir = self.dist_dir / "temp_build"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 2. Экспорт Векторов (GeoPackage)
            gpkg_path = build_dir / "vectors.gpkg"
            self.export_vectors(gpkg_path)

            # 3. Копирование Растров — все доступные годы в rasters/{year}/
            dst_rasters_root = build_dir / "rasters"
            dst_rasters_root.mkdir()
            for year in raster_years:
                src = self.public_rasters_dir / str(year)
                dst = dst_rasters_root / str(year)
                logger.info(f"Copying rasters {year} from {src}...")
                shutil.copytree(src, dst)

            # 4. SQL-скрипт для пересоздания схемы на стороне получателя
            shutil.copy2(self.settings.paths.create_assessment_schema, build_dir / "create_assessment_schema.sql")

            # 5. Манифест
            with open(build_dir / "manifest.json", "w") as f:
                f.write(self.create_manifest(raster_years, gpkg_path))

            # 6. Архивирование (ZIP)
            zip_filename = self.dist_dir / f"{package_name}.zip"
            logger.info(f"Creating archive: {zip_filename}...")

            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(build_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(build_dir)
                        zipf.write(file_path, arcname)

            logger.info(f"Package created successfully! Years: {raster_years}")
            print(f"OUTPUT: {zip_filename}")

        finally:
            # Чистим за собой
            if build_dir.exists():
                shutil.rmtree(build_dir)

def task_package():
    PackageTask().run()

if __name__ == "__main__":
    # См. пояснение в src/tasks/classify.py — без этого вызова
    # logger.info() при прямом запуске уходит в никуда.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    task_package()