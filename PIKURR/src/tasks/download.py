"""
Модуль загрузки тайлов с проверкой качества
"""
import os
import time
import random
import threading
import logging
import requests
import numpy as np
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Tuple
from PIL import Image
from io import BytesIO
from src.core.config import settings
# from ..core.config import Settings
from ..services.db import DatabaseService
from ..utils.geo import getTileIndex

logger = logging.getLogger(__name__)

# Хранилище для сессий (у каждого потока своя сессия requests)
thread_local = threading.local()

class DownloadTilesTask:
    def __init__(self):
        self.config = settings
        #self.db = DatabaseService(config.db)

        self.db = DatabaseService(settings) 
        


        self.tile_services = settings.tileservices
        # self.max_workers = 40  # Количество потоков для загрузки
        self.max_workers = 4  # Умеренное кол-во потоков для прокси
        self.delay_min = 0.1
        self.delay_max = 0.4

    def get_session(self):
        """Возвращает сессию requests, уникальную для текущего потока"""
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
            # Настраиваем заголовки для маскировки под gismap.by
            thread_local.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://gismap.by/next/',
                'Host': 'gismap.by',
                'Connection': 'keep-alive'
            })
        return thread_local.session



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
        # Обработка разных типов геометрии (Polygon/MultiPolygon)
        if geom['type'] == 'Polygon':
            coordinates = geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            # Берем первый полигон (обычно трапеция - это один квадрат)
            coordinates = geom['coordinates'][0][0]
        else:
            return (0,0,0,0)
        
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

        # Порядок источников: DZZ -> ESRI -> GOOGLE
        sources = [
            ('dzz', self.tile_services.dzz),
            ('esri', self.tile_services.esri),
            ('google', self.tile_services.google)
        ]

        # headers = {
        #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        #     'Referer': 'https://www.geodzz.by/izuchdzz/'
        # }

        # Имитация задержки перед обработкой тайла (снижаем RPS)
        time.sleep(random.uniform(self.delay_min, self.delay_max))
        
        session = self.get_session()

        for service_name, url_template in sources:
            try:
                # Обработка специального случая для DZZ
                if 'dzz' in service_name:
                    z_val = z - 6
                    if '{z-6}' in url_template:
                        url = url_template.replace('{z-6}', str(z_val)).format(x=x, y=y)
                    else:
                        url = url_template.format(x=x, y=y, z=z_val)
                else:
                    url = url_template.format(x=x, y=y, z=z)

                
                response = session.get(url, timeout=10)
                
                if response.status_code == 200:

                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'image' not in content_type and 'application/octet-stream' not in content_type:
                        continue # Прокси вернул HTML ошибку

                    try:
                        img = Image.open(BytesIO(response.content)).convert('RGB')
                        img_array = np.array(img)
                    except Exception:
                        continue # Битая картинка

                    # img = Image.open(response.raw)
                    # img_array = np.array(img)
                    
                    # Проверка качества изображения
                    if img_array.ndim != 3:
                        logger.debug(f"Invalid dimensions for {service_name} tile {x},{y}")
                        continue
                        
                    h, w, _ = img_array.shape
                    gray_ratio = np.sum(img_array[:,:,0] == img_array[:,:,1]) / (h * w)
                    
                    if gray_ratio < 0.7:  # Цветное изображение
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
                # for x in range(min_x, max_x + 1):
                #     for y in range(min_y, max_y + 1):
                #         executor.submit(self.process_tile, x, y, 17, trapeze_name)

                # Создаем задачи
                futures = []
                for x in range(min_x, max_x + 1):
                    for y in range(min_y, max_y + 1):
                        futures.append(executor.submit(self.process_tile, x, y, 17, trapeze_name))
                
                # Ждем завершения трапеции, чтобы не забить память миллионом задач
                for f in futures:
                    f.result()

def task_download():
    DownloadTilesTask().run()

if __name__ == "__main__":
    task_download()