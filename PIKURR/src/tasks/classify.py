import datetime
import logging
from pathlib import Path
from typing import List

import numpy as np
import rasterio
from rasterio.features import sieve
from skimage.morphology import closing, disk
from skimage.transform import resize
from tqdm import tqdm

from src.core.config import settings
from src.services.db import DatabaseService

# Настройка логгера
logger = logging.getLogger(__name__)

class ClassificationTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.trap_table = settings.dbtables.trap
        
        # Пути из конфига
        self.veget_dir = settings.paths.predictions_veget  # Вход: маска растительности
        self.usab_dir = settings.paths.predictions_usab    # Вход: используемость (GEE)
        self.final_dir = settings.paths.predictions_final  # Выход

    def get_trap_list(self) -> List[str]:
        """Получает список имен всех трапеций"""
        query = f"SELECT name FROM {self.trap_table}"
        try:
            df = self.db.execute_query(query)
            return df['name'].tolist()
        except Exception:
            # Fallback на случай, если колонка называется trapeze
            query = f"SELECT trapeze FROM {self.trap_table}"
            df = self.db.execute_query(query)
            return df['trapeze'].tolist()

    def get_target_years(self) -> range:
        """Определяет диапазон лет (текущий и 2 предыдущих)"""
        now = datetime.datetime.now()
        # Если месяц < 11, считаем, что сезон еще не закончился, берем прошлый год как текущий
        if now.month < 11:
            curyear = now.year - 1
        else:
            curyear = now.year
        return range(curyear - 2, curyear + 1)

    def process_trapeze(self, trap_id: str, years: range):
        """
        Объединяет маску растительности и данные об используемости.
        """
        land_mask_path = self.veget_dir / f"{trap_id}.tif"
        
        # 1. Загружаем маску растительности (Vegetation Mask)
        if not land_mask_path.exists():
            # logger.warning(f"No vegetation mask for {trap_id}")
            return

        try:
            with rasterio.open(land_mask_path) as src:
                land_mask_data = src.read(1) # Читаем первый канал
                profile = src.profile
        except Exception as e:
            logger.error(f"Error reading vegetation mask {trap_id}: {e}")
            return

        # 2. Загружаем данные используемости (Usability) за 3 года
        usab_data_list = []
        for year in years:
            usab_path = self.usab_dir / str(year) / f"{trap_id}.tif"
            
            if usab_path.exists():
                try:
                    with rasterio.open(usab_path) as src:
                        data = src.read(1)
                        usab_data_list.append(data)
                except Exception:
                    continue
        
        # Если нет данных ни за один год - считаем usability нулевым
        if not usab_data_list:
            combined_usab = np.zeros_like(land_mask_data, dtype=bool)
        else:
            # Логика: если активность была хотя бы в одном году (Logical OR)
            # np.vstack превратит список (N, H, W) в массив. any(axis=0) сплющит по годам.
            # Примечание: vstack требует одинаковых размерностей.
            # Если размеры GEE растров отличаются (они могут быть чуть разные), 
            # по-хорошему их надо ресайзить ДО стекинга.
            # В оригинале vstack делался в лоб. Повторяем, но добавляем resize, если размеры не совпадают.
            
            target_shape = usab_data_list[0].shape
            aligned_list = []
            for d in usab_data_list:
                if d.shape != target_shape:
                    # Ресайз до размера первого элемента (Nearest Neighbor для масок)
                    d = resize(d, target_shape, order=0, preserve_range=True, anti_aliasing=False)
                aligned_list.append(d)
                
            try:
                # Объединяем годы
                combined_usab = np.array(aligned_list).any(axis=0)
                
                # Морфология (из оригинала)
                # 1. Closing disk(1) - закрываем мелкие дыры
                combined_usab = closing(combined_usab, disk(1))
                
                # 2. Sieve - убираем шум (мелкие пятна < 10 пикселей)
                # sieve требует int, поэтому кастим в uint8
                combined_usab = sieve(combined_usab.astype(rasterio.uint8), 10, connectivity=4)
                
                # 3. Ресайз до размера маски растительности (Land Mask)
                # Оригинал использовал resize без параметров (что дает float [0..1]).
                # land_mask имеет высокое разрешение (тайлы), GEE - низкое (10м).
                # Поэтому ресайз обязателен.
                if combined_usab.shape != land_mask_data.shape:
                    combined_usab = resize(combined_usab, land_mask_data.shape, preserve_range=True)
            
            except Exception as e:
                logger.error(f"Error processing morphology for {trap_id}: {e}")
                combined_usab = np.zeros_like(land_mask_data)

        # 3. Финальная классификация
        # Логика: Берем маску растительности.
        # Если там Класс 3 (предположительно Поле/Пашня) И есть активность (Usability > 0)
        # То меняем класс на 5 (Обрабатываемая земля?)
        
        # combined_usab может быть float после resize, поэтому > 0 корректно
        mask_condition = (combined_usab > 0) & (land_mask_data == 3)
        land_mask_data[mask_condition] = 5

        # 4. Сохранение
        # Определяем папку текущего года (последний год в диапазоне)
        current_year = years[-1]
        output_dir = self.final_dir / str(current_year)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / f"{trap_id}.tif"
        
        # Обновляем профиль перед записью
        # Устанавливаем 255 как значение "Нет данных" (фон), чтобы 0 остался Лесом
        profile.update({
            'dtype': 'uint8',
            'nodata': 255,   # <--- 255 это фон
            'compress': 'lzw',
            'crs': rasterio.CRS.from_epsg(4326)
        })

        try:
            with rasterio.open(output_path, 'w', **profile) as dst:
                # Перед записью можно залить фон значением 255, если нужно,
                # но пока пишем как есть.
                dst.write(land_mask_data.astype(rasterio.uint8), 1)
        except Exception as e:
            logger.error(f"Error saving result {trap_id}: {e}")

    def run(self):
        trap_list = self.get_trap_list()
        years = self.get_target_years()
        
        print(f"Classification years range: {list(years)}")
        print(f"Target directory: {self.final_dir}")

        for trap in tqdm(trap_list, desc="Classifying"):
            self.process_trapeze(trap, years)

def task_classify():
    task = ClassificationTask()
    task.run()

if __name__ == "__main__":
    task_classify()