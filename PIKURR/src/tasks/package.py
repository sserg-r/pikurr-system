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
        """Экспорт View из PostGIS в GeoPackage через ogr2ogr"""
        logger.info(f"Exporting vectors to {output_gpkg.name}...")
        
        # Строка подключения для ogr2ogr
        # ВАЖНО: Пароль передаем через ENV, чтобы не светить в логах
        env = os.environ.copy()
        env["PGPASSWORD"] = self.settings.db.password
        
        conn_str = f"PG:dbname={self.settings.db.name} host={self.settings.db.host} port={self.settings.db.port} user={self.settings.db.user}"
        
        cmd = [
            "ogr2ogr",
            "-f", "GPKG",
            str(output_gpkg),
            conn_str,
            "-sql", f"SELECT * FROM {self.view_name}", # Экспортируем только готовое вью
            "-nln", "fields_assessment", # Имя слоя внутри GPKG
            "-overwrite"
        ]
        
        try:
            subprocess.run(cmd, env=env, check=True)
            logger.info("Vector export successful.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Vector export failed: {e}")
            raise e

    def create_manifest(self, zip_path: Path):
        """Создает файл описания пакета"""
        manifest = {
            "created_at": datetime.datetime.now().isoformat(),
            "year": self.get_target_year(),
            "version": "2.0",
            "contents": ["vectors.gpkg", "rasters/"]
        }
        return json.dumps(manifest, indent=2)

    def run(self):
        year = self.get_target_year()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        package_name = f"pikurr_update_{year}_{date_str}"
        
        # 1. Подготовка временной папки для сборки
        build_dir = self.dist_dir / "temp_build"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 2. Экспорт Векторов (GeoPackage)
            gpkg_path = build_dir / "vectors.gpkg"
            self.export_vectors(gpkg_path)
            
            # 3. Копирование Растров
            # Берем растры из predictions/geoserver_public/{year}
            src_raster_dir = self.public_rasters_dir / str(year)
            dst_raster_dir = build_dir / "rasters"
            
            if src_raster_dir.exists():
                logger.info(f"Copying rasters from {src_raster_dir}...")
                shutil.copytree(src_raster_dir, dst_raster_dir)
            else:
                logger.warning(f"No raster folder found: {src_raster_dir}")
                dst_raster_dir.mkdir()

            # 4. Манифест
            with open(build_dir / "manifest.json", "w") as f:
                f.write(self.create_manifest(build_dir))

            # 5. Архивирование (ZIP)
            zip_filename = self.dist_dir / f"{package_name}.zip"
            logger.info(f"Creating archive: {zip_filename}...")
            
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(build_dir):
                    for file in files:
                        file_path = Path(root) / file
                        # Сохраняем относительный путь внутри архива
                        arcname = file_path.relative_to(build_dir)
                        zipf.write(file_path, arcname)
                        
            logger.info("Package created successfully!")
            print(f"OUTPUT: {zip_filename}")

        finally:
            # Чистим за собой
            if build_dir.exists():
                shutil.rmtree(build_dir)

def task_package():
    PackageTask().run()

if __name__ == "__main__":
    task_package()