"""
Модуль загрузки тайлов с проверкой качества
"""

import os
import logging
import requests
import numpy as np
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Tuple
from PIL import Image
from src.core.config import settings
# from ..core.config import Settings
from ..services.db import DatabaseService
from ..utils.geo import getTileIndex

logger = logging.getLogger(__name__)

class DownloadTilesTask:
    def __init__(self):
        self.config = settings
        #self.db = DatabaseService(config.db)

        self.db = DatabaseService(settings) 
        


        self.tile_services = settings.tileservices
        self.max_workers = 40  # Количество потоков для загрузки

    def get_trapezes(self) -> pd.DataFrame:
        """Получение списка трапеций из БД с подтягиванием геометрии из разграфки"""
        
        # Алиасы таблиц для краткости
        t_task = self.config.dbtables.trap   # trapeze_serv
        t_geom = self.config.dbtables.razgr  # razgrafka (там лежит geom)
        
        # JOIN запрос: берем имя из задачи, а геометрию из разграфки
        # Предполагаем, что колонка name в trapeze_serv соответствует n10000 в razgrafka
        query = f"""
            SELECT 
                t.name, 
                ST_AsGeoJSON(r.geom) AS geojson 
            FROM {t_task} t
            JOIN {t_geom} r ON t.name = r.n10000
        """
        
        return self.db.execute_query(query)

    def calculate_tile_ranges(self, trapeze_geojson: str, zoom: int = 17) -> Tuple[int, int, int, int]:
        """Расчет диапазона тайлов для трапеции"""
        geom = json.loads(trapeze_geojson)
        coordinates = geom['coordinates'][0]  # Внешнее кольцо полигона
        
        # Вычисляем bounding box
        lons, lats = zip(*coordinates)
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        # Получаем индексы угловых тайлов
        min_x, min_y, _, _ = getTileIndex(max_lat, min_lon, zoom)  # Top-Left
        max_x, max_y, _, _ = getTileIndex(min_lat, max_lon, zoom)  # Bottom-Right
        
        return (min_x, max_x, min_y, max_y)

    def process_tile(self, x: int, y: int, z: int, trapeze_name: str):
        """Загрузка и валидация одного тайла"""
        # save_dir = Path(self.config.paths.data_dir) / trapeze_name
        save_dir = self.config.paths.tiles_dir / trapeze_name

        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{z}_{x}_{y}.jpg"

        if save_path.exists() and save_path.stat().st_size > 0:
            return  # Файл уже существует

        # Порядок источников по приоритету
        sources = [
            ('dzz', self.tile_services.dzz),
            ('esri', self.tile_services.esri),
            ('google', self.tile_services.google)
        ]

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.geodzz.by/izuchdzz/'
        }

        for service_name, url_template in sources:
            try:
                # Обработка специального случая для DZZ
                if service_name == 'dzz':
                    z_val = z - 6
                    url = url_template.replace('{z-6}', '{z}').format(x=x, y=y, z=z_val)
                else:
                    url = url_template.format(x=x, y=y, z=z)
                
                response = requests.get(url, headers=headers, stream=True, timeout=10)
                
                if response.status_code == 200:
                    img = Image.open(response.raw)
                    img_array = np.array(img)
                    
                    # Проверка качества изображения
                    if img_array.ndim != 3:
                        logger.debug(f"Invalid dimensions for {service_name} tile {x},{y}")
                        continue
                        
                    h, w, _ = img_array.shape
                    gray_ratio = np.sum(img_array[:,:,0] == img_array[:,:,1]) / (h * w)
                    
                    if gray_ratio < 0.2:  # Цветное изображение
                        img.save(save_path)
                        # logger.info(f"Saved tile {x},{y} from {service_name}")
                        logger.debug(f"Saved tile {x},{y} from {service_name}")
                        return
                    else:
                        # logger.warning(f"Poor quality tile from {service_name} at {x},{y}")
                        logger.debug(f"Poor quality tile from {service_name} at {x},{y}")
            except Exception as e:
                logger.error(f"Error downloading from {service_name}: {str(e)}")

        logger.error(f"Failed to download tile {x},{y} from all sources")

    def run(self):
        """Основной метод выполнения задачи"""
        trapezes_df = self.get_trapezes()
        logger.info(f"Found {len(trapezes_df)} trapezes for processing")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for _, row in trapezes_df.iterrows():
                trapeze_name = row['name']
                min_x, max_x, min_y, max_y = self.calculate_tile_ranges(row['geojson'])
                
                logger.info(f"Processing trapeze {trapeze_name} with {max_x-min_x+1}x{max_y-min_y+1} tiles")
                
                # Создаем задачи для каждого тайла
                for x in range(min_x, max_x + 1):
                    for y in range(min_y, max_y + 1):
                        executor.submit(self.process_tile, x, y, 17, trapeze_name)