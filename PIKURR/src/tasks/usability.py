import logging
from pathlib import Path
from typing import List

import numpy as np
import rasterio
from tqdm import tqdm

from src.core.config import settings
from src.services.db import DatabaseService
from src.services.gee import GEEService
from src.utils.analysis import calculate_usability_metric
from src.utils.timeutils import get_target_years

# Настройка логгера
logger = logging.getLogger(__name__)

class UsabilityTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.gee_service = GEEService()
        self.trap_table = settings.dbtables.trap
        # Добавляем таблицу с геометрией
        self.razgr_table = settings.dbtables.razgr
        self.output_root = settings.paths.predictions_usab

    def get_trap_list(self) -> List[str]:
        """Получает список имен всех трапеций для обработки"""
        # Пробуем получить имена из таблицы задач
        query = f"SELECT name FROM {self.trap_table}"
        try:
            df = self.db.execute_query(query)
            return df['name'].tolist()
        except Exception:
            # Fallback для старой схемы
            query = f"SELECT trapeze FROM {self.trap_table}"
            df = self.db.execute_query(query)
            return df['trapeze'].tolist()

    def get_trapeze_bbox(self, trap_name: str) -> List[float]:
        """
        Получает BBOX трапеции: [xmin, ymin, xmax, ymax]
        Берем геометрию из таблицы RAZGRAFKA, так как в trapeze_serv её нет.
        """
        query = f"""
            SELECT 
                ST_XMin(geom) as xmin, 
                ST_YMin(geom) as ymin, 
                ST_XMax(geom) as xmax, 
                ST_YMax(geom) as ymax
            FROM {self.razgr_table}
            WHERE n10000 = %(name)s
        """
        
        df = self.db.execute_query(query, {'name': trap_name})

        if df.empty:
            raise ValueError(f"Trapeze {trap_name} not found in {self.razgr_table}")
        
        row = df.iloc[0]
        return [row['xmin'], row['ymin'], row['xmax'], row['ymax']]

    def get_target_years(self) -> range:
        return get_target_years(count=3)

    def process_trapeze(self, trap_name: str, year: int, output_path: Path):
        try:
            bbox = self.get_trapeze_bbox(trap_name)
            
            # Получаем URL на скачивание временного ряда SCL
            url = self.gee_service.get_scl_series_url(year, bbox)
            
            if not url:
                # logger.warning(f"[{year}] {trap_name}: No data URL")
                return

            # Скачиваем "сырые" данные
            raw_result = self.gee_service.download_gee_data(url)
            raw_data = raw_result['data']
            profile = raw_result['profile']

            # Выполняем анализ
            usability_map = calculate_usability_metric(raw_data)
            
            # Сохраняем результат
            self.save_geotiff(usability_map, output_path, profile)
            
        except Exception as e:
            logger.error(f"Error processing {trap_name} for year {year}: {e}")

    def save_geotiff(self, data: np.ndarray, path: Path, src_profile: dict):
        """Сохраняет одноканальный результат"""
        profile = src_profile.copy()
        
        profile.update({
            'driver': 'GTiff',
            'dtype': 'uint8',
            'count': 1,
            'compress': 'lzw',
            'nodata': 0 
        })

        with rasterio.open(path, 'w', **profile) as dst:
            dst.write(data.astype(rasterio.uint8), 1)

    def run(self):
        years = self.get_target_years()
        trap_list = self.get_trap_list()
        
        logger.info(f"Target years: {list(years)}")
        logger.info(f"Total trapezes: {len(trap_list)}")

        for year in years:
            year_dir = self.output_root / str(year)
            year_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Processing year: {year}")
            
            for trap in tqdm(trap_list, desc=f"Year {year}"):
                output_path = year_dir / f"{trap}.tif"
                
                if output_path.exists():
                    continue
                
                self.process_trapeze(trap, year, output_path)

def task_usability():
    task = UsabilityTask()
    task.run()

if __name__ == "__main__":
    task_usability()