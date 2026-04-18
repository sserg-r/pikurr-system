"""
Модуль сохранения статистики полей в базу данных
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
from shapely.geometry import shape
from tqdm import tqdm

import datetime

from src.core.config import settings
from src.services.db import DatabaseService
from src.utils.postclassify import calculate_zonal_stats
from src.utils.timeutils import get_target_year

logger = logging.getLogger(__name__)


class SaveStatsTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.afields = settings.dbtables.afields
        self.razgr = settings.dbtables.razgr
        self.final_dir = settings.paths.predictions_final

    def get_target_year(self) -> int:
        return get_target_year()

    def get_fields(self) -> pd.DataFrame:
        """Получает список полей с геометриями и фреймами"""
        query = f"""
        SELECT
            {self.afields}.nr_user,
            ST_AsGeoJSON({self.afields}.geom) as geom_json,
            array_agg({self.razgr}.n10000) as frames
        FROM {self.afields}
        JOIN {self.razgr} ON ST_intersects({self.afields}.geom, {self.razgr}.geom)
        GROUP BY {self.afields}.nr_user, {self.afields}.geom
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
        for frame in frames:
            tiff_path = year_dir / f"{frame}.tif"
            if tiff_path.exists():
                tiff_paths.append(str(tiff_path))

        if not tiff_paths:
            return

        # --- ИЗМЕНЕНИЕ: Передаем СТРОКУ, а не объект ---
        # geom_json_str приходит из PostGIS как текст
        stats = calculate_zonal_stats(geom_json_str, tiff_paths)
        # stats = {'0': 0.1, '5': 0.9}
        # -----------------------------------------------

        if not stats:
            return

        self.save_stats(nr_user, year, stats)

    def run(self):
        year = self.get_target_year()
        fields_df = self.get_fields()
        total_fields = len(fields_df)

        logger.info(f"Processing {len(fields_df)} fields for year {year}")

        for _, field_row in tqdm(fields_df.iterrows(), total=total_fields, desc="Saving stats"):
            try:
                self.process_field(field_row, year)
            except Exception as e:
                logger.error(f"Error processing field {field_row['nr_user']}: {e}")
            


def task_save_db():
    task = SaveStatsTask()
    task.run()


if __name__ == "__main__":
    task_save_db()