import logging
import math
import subprocess
from pathlib import Path
from typing import List, Dict

import numpy as np
import rasterio
from rasterio.features import geometry_mask, rasterize
from rasterio.transform import Affine
from shapely import wkb
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

from src.core.config import settings
from src.services.db import DatabaseService
from src.utils.progress import ProgressReporter
from src.utils.timeutils import get_target_year

logger = logging.getLogger(__name__)

# round29, блок B: пересборка в Cloud-Optimized GeoTIFF (тайлы+обзоры
# одной командой) — параметры подобраны и проверены в round28 (блок C,
# рычаг 1): данные категориальные (несколько дискретных классов, не
# непрерывный тон), поэтому передискретизация обзоров — nearest, не
# average (иначе появятся несуществующие "смешанные" классы).
# BLOCKSIZE=512 и COMPRESS=LZW — так же, как round28 проверил на всей
# мозаике (checksum до/после идентичен, объём меньше исходника).
_COG_TRANSLATE_OPTS = [
    "-of", "COG",
    "-co", "COMPRESS=LZW",
    "-co", "RESAMPLING=NEAREST",
    "-co", "BLOCKSIZE=512",
]


def _convert_to_cog(path: Path) -> None:
    """round29, блок B: пересобирает GeoTIFF по пути `path` в COG на
    месте (через временный файл — gdal_translate не пишет поверх
    своего же источника). Вызывается ПОСЛЕ того, как маскирование
    (process_trapeze) уже записало обычный GeoTIFF — сама математика
    маски и merge_imageset не меняются, COG — чисто финальный шаг
    формата хранения."""
    tmp_path = path.with_suffix(".cog_tmp.tif")
    cmd = ["gdal_translate", *_COG_TRANSLATE_OPTS, str(path), str(tmp_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"gdal_translate (COG) не удался для {path}: {result.stderr}")
        tmp_path.unlink(missing_ok=True)
        return
    tmp_path.replace(path)

_Z17_PX = 256 * 2 ** 17  # ширина мира в пикселях сетки тайлов z17


def _lonlat_to_global_px(lon, lat):
    """lon/lat (EPSG:4326) -> глобальные пиксели Web Mercator z17 (общие для всех листов)."""
    x = (lon + 180.0) / 360.0 * _Z17_PX
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * _Z17_PX
    return x, y


def sheet_polygon_mask(polygon, transform, shape) -> np.ndarray:
    """round57, D3: маска «пиксель принадлежит полигону листа» (центр пикселя внутри).

    Строится в ГЛОБАЛЬНЫХ пикселях z17, а не по геопривязке конкретного растра:
    растры соседних листов привязаны к одной целочисленной сетке (угол — целое число
    пикселей), а вот широта пикселя по линейной геопривязке у соседей слегка
    различается; по геопривязке пиксель на общей границе мог бы достаться обоим
    листам. В глобальной сетке общая граница — одни и те же вершины, пиксель
    принадлежит ровно одному листу."""
    x0 = round((transform.c + 180.0) / 360.0 * _Z17_PX)
    y0 = round(_lonlat_to_global_px(0.0, transform.f)[1])
    def _to_px(xs, ys, zs=None):
        pts = [_lonlat_to_global_px(x, y) for x, y in zip(xs, ys)]
        return tuple(zip(*pts))
    poly_px = shp_transform(_to_px, polygon)
    return geometry_mask([mapping(poly_px)], out_shape=shape,
                         transform=Affine(1.0, 0.0, x0, 0.0, 1.0, y0), invert=True)


class ExportTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.trap_table = settings.dbtables.trap
        self.razgr_table = settings.dbtables.razgr
        self.final_dir = settings.paths.predictions_final
        self.progress: ProgressReporter | None = None
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

    def get_sheet_polygon(self, trap_name: str):
        """Полигон листа из razgrafka (None, если листа там нет)."""
        df = self.db.execute_query(
            f"SELECT ST_AsBinary(geom) AS geom_wkb FROM {self.razgr_table} WHERE n10000 = %(name)s",
            {'name': trap_name})
        if df.empty:
            return None
        return wkb.loads(bytes(df.iloc[0]['geom_wkb']))

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

                # round57, D3: публичный растр листа — только внутри полигона этого листа,
                # вне полигона 0 (прозрачно). Холст листа шире полигона (целые тайлы z17,
                # до +255 пикс), раньше полоса за полигоном попадала в публичный растр и
                # перекрывалась растром соседа; мозаика GeoServer показывала произвольный лист.
                sheet_poly = self.get_sheet_polygon(trap_name)
                if sheet_poly is not None:
                    masked_data = masked_data * sheet_polygon_mask(sheet_poly, src.transform, (src.height, src.width))
                else:
                    logger.warning(f"Лист {trap_name} не найден в razgrafka — маска по полигону не применена")
                
                # Возвращаем в uint8 (если влезает)
                masked_data = masked_data.astype(np.uint8)
                
                # Обновляем nodata. Теперь 0 - это прозрачность (фон).
                profile.update(nodata=0)
                
                with rasterio.open(out_path, 'w', **profile) as dst:
                    dst.write(masked_data, 1)

                # round29, блок B: COG — тайлинг+обзоры+сжатие одной
                # командой, после того как маска уже записана обычным
                # GeoTIFF выше (математика маски не меняется).
                _convert_to_cog(out_path)

        except Exception as e:
            logger.error(f"Error exporting {trap_name}: {e}")

    def run(self):
        year = self.get_target_year()
        trapezes = self.get_trapezes()
        
        logger.info(f"Exporting {len(trapezes)} trapezes for year {year}")
        logger.info(f"Target directory {self.final_dir / str(year)}")
        
        # Прогресс — через logging (ProgressReporter), как в остальных задачах;
        # tqdm писал в stderr, панель управления его не перехватывает.
        self.progress = ProgressReporter(
            name="export", total_outer=len(trapezes), logger=logger,
            outer_name="лист", inner_name="листы", rate_unit="лист",
        )
        for trap in trapezes:
            self.progress.start_outer(trap, total_inner=1)
            self.process_trapeze(trap, year)
            self.progress.tick(1)
            self.progress.finish_outer()
        self.progress.finish()
        logger.info("Export complete.")

def task_publicdata():
    ExportTask().run()

if __name__ == "__main__":
    # См. пояснение в src/tasks/classify.py — без этого вызова
    # logger.info() при прямом запуске уходит в никуда.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    task_publicdata()