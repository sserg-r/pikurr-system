"""
Модуль сохранения статистики полей в базу данных
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
from shapely.geometry import shape
from tqdm import tqdm

from src.core.config import settings
from src.services.db import DatabaseService
from src.utils.postclassify import calculate_zonal_stats

logger = logging.getLogger(__name__)


class SaveStatsTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.afields = settings.dbtables.afields
        self.razgr = settings.dbtables.razgr
        self.final_dir = settings.paths.predictions_final

    def get_target_year(self) -> int:
        """Определяет текущий год для статистики"""
        now = datetime.datetime.now()
        if now.month < 11:
            return now.year - 1
        else:
            return now.year

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

    def generate_html(self, stats: Dict[str, float]) -> str:
        """Генерирует HTML описание на основе статистики"""
        labels = {0: 'forest', 1: 'bushes', 2: 'bushy', 3: 'meadows', 4: 'other', 5: 'tillage'}
        palette = {0: "#4e7626", 1: "#30b646", 2: "#acf189", 3: "#deffcf", 4: "#f8f5c4", 5: "#cba27b"}

        descr = '<table><thead><tr><td>veg_type</td><td>percentage</td></tr></thead><tbody>'
        line = '<tr><td style="background-color:{0}"> {1} </td><td>{2}</td></tr>'

        for class_str, percentage in stats.items():
            class_id = int(class_str)
            if class_id in labels:
                perc_str = f"{percentage:.2f}"
                descr += line.format(palette[class_id], labels[class_id], perc_str)

        descr += '</tbody></table>'
        return descr

    def save_stats(self, fid_ext: int, year: int, stats: Dict[str, float], description: str):
        """Сохраняет статистику в таблицу assessment"""
        stats_json = json.dumps(stats)
        updated_at = datetime.datetime.now()

        # ИСПОЛЬЗУЕМ ИМЕНОВАННЫЕ ПАРАМЕТРЫ (:param)
        query = """
        INSERT INTO assessment (fid_ext, year, stats, description, updated_at)
        VALUES (:fid_ext, :year, :stats, :description, :updated_at)
        ON CONFLICT (fid_ext, year) DO UPDATE SET
            stats = EXCLUDED.stats,
            description = EXCLUDED.description,
            updated_at = EXCLUDED.updated_at
        """

        # Передаем СЛОВАРЬ
        params = {
            'fid_ext': fid_ext,
            'year': year,
            'stats': stats_json,
            'description': description,
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

        html_description = self.generate_html(stats)
        # html_description='trash'
        # print(stats)
        # print(html_description)
        
        self.save_stats(nr_user, year, stats, html_description)

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