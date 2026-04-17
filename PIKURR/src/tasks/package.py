import datetime
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

    def create_manifest(self, years: list[int]):
        """Создает файл описания пакета"""
        latest_year = max(years) if years else self.get_target_year()
        manifest = {
            "created_at": datetime.datetime.now().isoformat(),
            "year": latest_year,        # последний год (для совместимости)
            "years": years,             # все годы, включённые в пакет
            "version": "2.0",
            "contents": ["vectors.gpkg", "rasters/"]
        }
        return json.dumps(manifest, indent=2)

    def run(self):
        # Определяем доступные годы по папкам с TIF
        raster_years = self.collect_raster_years()
        if not raster_years:
            logger.warning("Не найдено ни одной папки с TIF-файлами. Растры в пакет не войдут.")
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
                f.write(self.create_manifest(raster_years))

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
    task_package()