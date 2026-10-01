"""
Модуль сохранения статистики полей в базу данных
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
from shapely import wkb
from shapely.geometry import shape

import datetime

from src.core.config import settings
from src.services.db import DatabaseService
from src.utils.postclassify import calculate_zonal_stats
from src.utils.progress import ProgressReporter
from src.utils.timeutils import get_target_year

logger = logging.getLogger(__name__)


class SaveStatsTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.afields = settings.dbtables.afields
        self.razgr = settings.dbtables.razgr
        self.final_dir = settings.paths.predictions_final
        self.progress: ProgressReporter | None = None
        self.sheet_polygons: dict = {}

    def get_target_year(self) -> int:
        return get_target_year()

    def get_sheet_polygons(self) -> dict:
        """Полигоны листов (razgrafka) для маскирования растра листа его полигоном."""
        df = self.db.execute_query(
            f"SELECT n10000, ST_AsBinary(geom) AS geom_wkb FROM {self.razgr}"
        )
        return {row['n10000']: wkb.loads(bytes(row['geom_wkb'])) for _, row in df.iterrows()}

    def get_fields(self) -> pd.DataFrame:
        """Получает список участков с геометриями и фреймами (листами).

        round57, D4: код nr_user с несколькими полигонами — один кадастровый
        участок, разбитый на части: геометрия — объединение частей
        (ST_Union, ST_Multi), листы — все, пересекающие объединённую геометрию,
        одна строка на nr_user. Раньше каждый полигон шёл отдельной строкой, и
        в assessment оставался результат только последней обработанной части.
        Участок из одной части не пересобирается (берётся его геометрия как есть).
        Листы упорядочены по имени (round57, D2)."""
        query = f"""
        WITH u AS (
            SELECT nr_user,
                   CASE WHEN count(*) > 1
                        THEN ST_Multi(ST_Union(geom))
                        ELSE ST_Multi((array_agg(geom))[1])
                   END AS geom
            FROM {self.afields}
            GROUP BY nr_user
        )
        SELECT
            u.nr_user,
            ST_AsGeoJSON(u.geom) as geom_json,
            array_agg({self.razgr}.n10000 ORDER BY {self.razgr}.n10000) as frames
        FROM u
        JOIN {self.razgr} ON ST_intersects(u.geom, {self.razgr}.geom)
        GROUP BY u.nr_user, u.geom
        """
        return self.db.execute_query(query)

    def save_stats(self, fid_ext: int, year: int, stats: Dict[str, float]):
        """Сохраняет статистику в таблицу assessment"""
        stats_json = json.dumps(stats)
        updated_at = datetime.datetime.now()

        query = """
        INSERT INTO assessment (fid_ext, year, stats, updated_at)
        VALUES (:fid_ext, :year, :stats, :updated_at)
        ON CONFLICT (fid_ext, year) DO UPDATE SET
            stats = EXCLUDED.stats,
            updated_at = EXCLUDED.updated_at
        """

        params = {
            'fid_ext': fid_ext,
            'year': year,
            'stats': stats_json,
            'updated_at': updated_at
        }

        self.db.execute(query, params)

    def process_field(self, field_row, year: int):
        """Обрабатывает одно поле"""
        nr_user = field_row['nr_user']
        geom_json_str = field_row['geom_json'] # Это строка (str)
        frames = field_row['frames']

        year_dir = self.final_dir / str(year)
        tiff_paths = []
        polygons = []
        for frame in frames:
            tiff_path = year_dir / f"{frame}.tif"
            if tiff_path.exists():
                tiff_paths.append(str(tiff_path))
                polygons.append(self.sheet_polygons[frame])

        if not tiff_paths:
            return

        # --- ИЗМЕНЕНИЕ: Передаем СТРОКУ, а не объект ---
        # geom_json_str приходит из PostGIS как текст
        stats = calculate_zonal_stats(geom_json_str, tiff_paths, sheet_polygons=polygons)
        # stats = {'0': 0.1, '5': 0.9}
        # -----------------------------------------------

        if not stats:
            return

        self.save_stats(nr_user, year, stats)

    def run(self):
        year = self.get_target_year()
        fields_df = self.get_fields()
        self.sheet_polygons = self.get_sheet_polygons()
        total_fields = len(fields_df)

        logger.info(f"Processing {len(fields_df)} fields for year {year}")

        # Прогресс — через logging (ProgressReporter), как в остальных задачах;
        # tqdm писал в stderr, панель управления его не перехватывает.
        self.progress = ProgressReporter(
            name="save_db", total_outer=total_fields, logger=logger,
            outer_name="участок", inner_name="участки", rate_unit="участок",
        )
        for _, field_row in fields_df.iterrows():
            self.progress.start_outer(str(field_row['nr_user']), total_inner=1)
            try:
                self.process_field(field_row, year)
                self.progress.tick(1)
            except Exception as e:
                logger.error(f"Error processing field {field_row['nr_user']}: {e}")
                self.progress.tick_failed(1)
            self.progress.finish_outer()
        self.progress.finish()


def task_save_db():
    task = SaveStatsTask()
    task.run()


if __name__ == "__main__":
    # См. пояснение в src/tasks/classify.py — без этого вызова
    # logger.info() при прямом запуске уходит в никуда.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    task_save_db()