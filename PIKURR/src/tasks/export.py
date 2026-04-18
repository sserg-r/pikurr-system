import logging
from pathlib import Path
from typing import List, Dict

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely import wkb
from tqdm import tqdm

from src.core.config import settings
from src.services.db import DatabaseService
from src.utils.timeutils import get_target_year

logger = logging.getLogger(__name__)

class ExportTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.trap_table = settings.dbtables.trap
        self.final_dir = settings.paths.predictions_final
        # Сохраняем в public_root (или predictions/public, если в конфиге нет)
        self.public_dir = settings.paths.public_root 
        
        # Таблица транслитерации
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
        return get_target_year()

    def get_trapezes(self) -> List[str]:
        query = f"SELECT name FROM {self.trap_table}"
        try:
            df = self.db.execute_query(query)
            return df['name'].tolist()
        except Exception:
            query = f"SELECT trapeze FROM {self.trap_table}"
            df = self.db.execute_query(query)
            return df['trapeze'].tolist()

    def get_field_geometries(self, trap_name: str) -> List:
        """
        Получает геометрию полей (agrifields).
        """
        # ИСПОЛЬЗУЕМ %(name)s ВМЕСТО :name ДЛЯ PANDAS/PSYCOPG2
        query_safe = f"""
            SELECT ST_AsBinary(a.geom) as geom_wkb
            FROM agrifields a 
            JOIN razgrafka r ON a.geom && r.geom 
            WHERE r.n10000 = %(name)s
        """
        
        # Передаем словарь параметров
        df = self.db.execute_query(query_safe, {'name': trap_name})
        
        geoms = []
        for _, row in df.iterrows():
            try:
                g = wkb.loads(bytes(row['geom_wkb']))
                geoms.append(g)
            except Exception as e:
                logger.warning(f"Error parsing WKB for {trap_name}: {e}")
                
        return geoms

    def process_trapeze(self, trap_name: str, year: int):
        source_path = self.final_dir / str(year) / f"{trap_name}.tif"
        
        if not source_path.exists():
            return

        # Транслитерация имени для выходного файла
        out_name = trap_name.translate(self.trans_tab)
        out_dir = self.public_dir / str(year)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{out_name}.tif"

        try:
            # Получаем геометрии полей для маски
            geoms = self.get_field_geometries(trap_name)
            
            if not geoms:
                # Если полей нет, но трапеция есть? 
                # В оригинале: просто копировали? Или падали?
                # В оригинале rasterize(geoms) с пустым списком выдаст нули.
                # Значит, будет пустой (черный) растр.
                # Логичнее пропустить.
                logger.debug(f"No fields intersect trapeze {trap_name}")
                return

            with rasterio.open(source_path) as src:
                profile = src.profile.copy()
                data = src.read(1) # (H, W)
                
                # Создаем маску: 1 внутри полей, 0 снаружи
                # fill=0, default_value=1
                mask = rasterize(
                    geoms,
                    out_shape=(src.height, src.width),
                    transform=src.transform,
                    fill=0,
                    default_value=1,
                    all_touched=True,
                    dtype=np.uint8
                )
                
                # Применяем маску
                # В оригинале было: data = (src.read()[0] + 1) * g
                # Зачем +1? Видимо, чтобы сдвинуть классы 0..5 -> 1..6, и использовать 0 как прозрачность?
                # Если 0 был Лес, он станет 1. А фон (который был 0) останется 0.
                # Это разумно.
                
                # НО! Мы уже исправили данные:
                # У нас 0 = Лес, 255 = Фон.
                # Если мы умножим на mask (где 0 - фон), то фон станет 0.
                # А Лес (0) * 1 = 0.
                # То есть Лес сольется с Фоном.
                
                # Чтобы сохранить Лес, нужно сдвинуть данные (+1).
                # Тогда Лес=1, Фон=0 (от маски).
                
                masked_data = (data.astype(np.uint16) + 1) * mask
                
                # Возвращаем в uint8 (если влезает)
                masked_data = masked_data.astype(np.uint8)
                
                # Обновляем nodata. Теперь 0 - это прозрачность (фон).
                profile.update(nodata=0)
                
                with rasterio.open(out_path, 'w', **profile) as dst:
                    dst.write(masked_data, 1)
                    
        except Exception as e:
            logger.error(f"Error exporting {trap_name}: {e}")

    def run(self):
        year = self.get_target_year()
        trapezes = self.get_trapezes()
        
        logger.info(f"Exporting {len(trapezes)} trapezes for year {year}")
        logger.info(f"Target directory {self.final_dir / str(year)}")
        
        for trap in tqdm(trapezes, desc="Exporting Public Data"):
            self.process_trapeze(trap, year)
        logger.info("Export complete.")

def task_publicdata():
    ExportTask().run()

if __name__ == "__main__":
    task_publicdata()