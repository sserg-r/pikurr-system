import json
import logging
from pathlib import Path
import numpy as np
import rasterio
from PIL import Image

from src.services.db import DatabaseService
from src.services.inference import InferenceService
from src.core.config import settings
from src.utils.image import merge_tiles, split_image, merge_imageset
from src.utils.geo import get_bbox_for_tileset, get_tile_range_for_bbox
from src.utils.progress import ProgressReporter

logger = logging.getLogger(__name__)

class SegmentationTask:
    def __init__(self):
        self.db = DatabaseService(settings)
        self.inference_service = InferenceService()
        self.trap_table = settings.dbtables.trap
        self.root_tiles_dir = settings.paths.tiles_dir
        self.predictions_dir = settings.paths.predictions_veget

        # Индексы классов (для читаемости)
        self.CLS_FOREST = 0
        self.CLS_BUSHES = 1
        self.CLS_BUSHY = 2
        self.CLS_MEADOW = 3
        self.CLS_OTHER = 4
        self.progress: ProgressReporter | None = None


    def get_trap_list(self):
        query = f"SELECT name FROM {self.trap_table}"
        try:
            df = self.db.execute_query(query)
            return df['name'].tolist()
        except Exception:
            query = f"SELECT trapeze FROM {self.trap_table}"
            df = self.db.execute_query(query)
            return df['trapeze'].tolist()

    def _predict_full_canvas(self, image_arr: np.ndarray, overlap=30) -> np.ndarray:
        """Режет, предсказывает, клеит. Возвращает маску (H, W)."""
        slices = split_image(image_arr, 256, overlap=overlap)
        
        # Нормализация
        batch = slices['image_batch'] / 255.0
        
        # Инференс
        predictions = self.inference_service.predict_batch(batch)
        if self.progress is not None:
            self.progress.tick(batch.shape[0])

        # Argmax
        pred_mask = predictions.argmax(axis=3)[..., None]
        
        # Сборка
        # crop_size передаем как (H, W) из shape
        assembled_pil = merge_imageset(
            pred_mask, 
            slices['assembly_pattern'], 
            crop_size=image_arr.shape[:2], 
            margin=overlap
        )
        
        return np.asarray(assembled_pil)

    def get_sheet_tile_range(self, trap_name: str, z: int = 17) -> tuple[int, int, int, int] | None:
        """Истинный диапазон тайлов листа (min_x, max_x, min_y, max_y) из
        геометрии `razgrafka` — не зависит от того, что физически докачано.
        Закрывает регрессию раунда 13 (задача 2, раунд 14): там канвас
        собирался только по bbox присутствующих файлов, и лист вроде
        `O-35-142-В-б-3` (398/672 тайлов отсутствуют за пределами этого
        bbox, не внутри) получал канвас меньше истинного размера — без
        пометки, что почти 60% площади вообще отсутствует. None, если
        геометрия не нашлась (вызывающий код откатывается на старое
        поведение — вывод диапазона из присутствующих файлов)."""
        query = (
            "SELECT ST_XMin(geom) AS min_lon, ST_YMin(geom) AS min_lat, "
            "ST_XMax(geom) AS max_lon, ST_YMax(geom) AS max_lat "
            "FROM razgrafka WHERE n10000 = %(name)s"
        )
        try:
            df = self.db.execute_query(query, params={"name": trap_name})
            if df.empty:
                logger.error(f"{trap_name}: не найден в razgrafka, диапазон тайлов не определён")
                return None
            row = df.iloc[0]
            return get_tile_range_for_bbox(
                float(row["min_lon"]), float(row["min_lat"]),
                float(row["max_lon"]), float(row["max_lat"]), z=z,
            )
        except Exception as e:
            logger.error(f"{trap_name}: не удалось получить границу из razgrafka: {e}")
            return None

    def process_trapeze(self, tile_dir: Path, output_path: Path):
        tile_range = self.get_sheet_tile_range(tile_dir.name)
        gaps_path = tile_dir.parent / f"{tile_dir.name}_gaps.json"
        canvas_pil = merge_tiles(str(tile_dir), gaps_out_path=gaps_path, tile_range=tile_range)
        if canvas_pil is None:
            return

        if gaps_path.exists():
            try:
                with open(gaps_path, encoding="utf-8") as f:
                    gaps_info = json.load(f)
                logger.warning(
                    f"{tile_dir.name}: {gaps_info['missing_count']} недостающих тайлов "
                    f"из {gaps_info['expected_tiles']} "
                    f"({100 * gaps_info['missing_fraction']:.2f}% плейсхолдер-пикселей) — "
                    f"см. {gaps_path.name}"
                )
            except (OSError, json.JSONDecodeError, KeyError) as e:
                logger.error(f"Не удалось прочитать {gaps_path} для лога: {e}")

        # Оригинал (Scale 1.0)
        canvas_full = np.asarray(canvas_pil)

        # 1. High-Res Inference
        mask_high = self._predict_full_canvas(canvas_full, overlap=30)
        
        # 2. Low-Res Inference (Context)
        # Сжимаем в 2 раза
        w, h = canvas_pil.size
        new_size = (w // 2, h // 2)
        canvas_small = canvas_pil.resize(new_size, resample=Image.BILINEAR)
        canvas_small_arr = np.asarray(canvas_small)
        
        mask_low_small = self._predict_full_canvas(canvas_small_arr, overlap=30)
        
        # Разжимаем обратно (Nearest Neighbor для классов)
        mask_low_pil = Image.fromarray(mask_low_small).resize((w, h), resample=Image.NEAREST)
        mask_low = np.array(mask_low_pil)

        # 3. Слияние (Smart Context Fix)
        # Если High=Other, а Context!=Other -> верим Контексту
        final_mask = mask_high.copy()

        mask_is_other_high=(final_mask == self.CLS_OTHER)
        
        fix_condition = (mask_high == self.CLS_OTHER) & (mask_low != self.CLS_OTHER)
        final_mask[fix_condition] = mask_low[fix_condition]

        # 4. Цветовая Коррекция ("Last Resort" для огромных полей)
        # Если после всего этого мы все еще видим "Прочее" (4), 
        # но пиксель явно зеленый или коричневый -> меняем принудительно.
        
        img_int = canvas_full.astype(np.int16)
        R, G, B = img_int[:,:,0], img_int[:,:,1], img_int[:,:,2]

        # Зелень
        is_green = (1.82 * G - R - B) > 0
        
        # Почва (грубая эвристика): Красный и Зеленый доминируют над Синим
        is_soil = (R > (B + 20)) & (G > (B + 10))

        # ВОДА         
        is_water_blue = (B > (R)) & (B*1.1 > G)

        
        mask_is_other = (final_mask == self.CLS_OTHER)
        mask_is_forest = ((final_mask == self.CLS_FOREST) | (final_mask == self.CLS_BUSHES))
        
        # Исправляем Зеленое -> Луг
        final_mask[mask_is_other & is_green & ~is_water_blue] = self.CLS_MEADOW
        
        # Исправляем Почву -> Пашня (или Луг, если хотите безопаснее)
        final_mask[mask_is_other & is_soil & ~is_water_blue] = self.CLS_MEADOW
        
        # исправляем воду
        # final_mask[mask_is_other_high & is_water_blue & ~is_green] = self.CLS_OTHER
        final_mask[mask_is_other_high & ~is_green] = self.CLS_OTHER

        self.save_as_geotiff(final_mask, tile_dir, output_path, tile_range=tile_range)

    def save_as_geotiff(self, image: np.ndarray, tile_dir: Path, output_path: Path, tile_range=None):
        try:
            if tile_range is not None:
                min_x, max_x, min_y, max_y = tile_range
                # синтетические "имена тайлов" — get_bbox_for_tileset нужен только
                # их разбор z_x_y, на диске эти файлы существовать не обязаны.
                bbox = get_bbox_for_tileset([f"17_{min_x}_{min_y}", f"17_{max_x}_{max_y}"], z=17)
            else:
                tile_paths = [str(p) for p in tile_dir.glob('*.*')]
                bbox = get_bbox_for_tileset(tile_paths, z=17)
            transform = rasterio.transform.from_bounds(
                west=bbox['west'], south=bbox['south'], 
                east=bbox['east'], north=bbox['north'],
                width=image.shape[1], height=image.shape[0]
            )
            profile = {
                'driver': 'GTiff', 'dtype': 'uint8', 'nodata': None,
                'width': image.shape[1], 'height': image.shape[0], 'count': 1,
                'crs': rasterio.CRS.from_epsg(4326),
                'transform': transform, 'compress': 'lzw'
            }
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(image.astype('uint8'), 1)
        except Exception as e:
            logger.error(f"Failed to save GeoTIFF: {e}")

    def run(self):
        trap_list = self.get_trap_list()
        self.predictions_dir.mkdir(parents=True, exist_ok=True)

        to_process = [
            trap for trap in trap_list
            if (self.root_tiles_dir / trap).exists()
            and any((self.root_tiles_dir / trap).iterdir())
            and not (self.predictions_dir / f"{trap}.tif").exists()
        ]
        self.progress = ProgressReporter(
            name="segmentate", total_outer=len(to_process), logger=logger,
            outer_name="лист", inner_name="фрагменты", rate_unit="фрагмент",
        )

        for trap in to_process:
            pred_path = self.predictions_dir / f"{trap}.tif"
            tiles_dir = self.root_tiles_dir / trap
            self.progress.start_outer(trap)
            try:
                self.process_trapeze(tiles_dir, pred_path)
            except Exception as e:
                logger.error(f"Error processing {trap}: {e}")
            self.progress.finish_outer()

        self.progress.finish()

def task_segmentate():
    SegmentationTask().run()

if __name__ == "__main__":
    # При запуске "python -m src.tasks.X" напрямую (docs/deploy-etl.md,
    # Вариант Б) логирование иначе не настроено нигде, кроме pipeline.py —
    # без этого весь logger.info() (включая ProgressReporter) уходит в
    # никуда, и прогресс/ошибки не видны в `docker logs`.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    task_segmentate()