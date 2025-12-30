from pathlib import Path
import numpy as np
import rasterio
from tqdm import tqdm
from src.services.db import DatabaseService
from src.services.inference import InferenceService
# Импортируем созданный экземпляр settings (маленькими буквами), а не класс
from src.core.config import settings 
from src.utils.image import merge_tiles, split_image, merge_imageset
from src.utils.geo import get_bbox_for_tileset
from src.utils.geo import get_bbox_for_tileset_mercator 

class SegmentationTask:
    def __init__(self):
        # ИСПРАВЛЕНИЕ: Передаем объект settings целиком, а не settings.db
        # DatabaseService внутри сам возьмет settings.db.dsn
        self.db = DatabaseService(settings) 
        
        # Инференс сервис инициализируется сам через импортированные settings
        self.inference_service = InferenceService()
        
        self.trap_table = settings.dbtables.trap
        # self.root_tiles_dir = settings.paths.temp
        # self.root_tiles_dir = settings.paths.data_dir 
        self.root_tiles_dir = settings.paths.tiles_dir
        self.predictions_dir = settings.paths.predictions_veget

    def get_trap_list(self):
        query = f"SELECT name FROM {self.trap_table}"
        df = self.db.execute_query(query)
        return df['name'].tolist()

    def run(self):
        trap_list = self.get_trap_list()
        self.predictions_dir.mkdir(parents=True, exist_ok=True)

        for trap in tqdm(trap_list, desc="Processing trapezoids"):
            pred_path = self.predictions_dir / f"{trap}.tif"
            tiles_dir = self.root_tiles_dir / trap

            if not tiles_dir.exists() or not any(tiles_dir.iterdir()):
                print(f"[WARNING] Skipping {trap}: Directory empty or not found: {tiles_dir}")
                continue

            # Проверяем наличие тайлов
            if not tiles_dir.exists() or not any(tiles_dir.iterdir()):
                continue

            if not pred_path.exists():
                try:
                    self.process_trapeze(tiles_dir, pred_path)
                except Exception as e:
                    print(f"Error processing {trap}: {e}")
                    # Можно добавить traceback для отладки
                    # import traceback; traceback.print_exc()

    def process_trapeze(self, tile_dir: Path, output_path: Path):
        canvas = merge_tiles(str(tile_dir))
        
        if canvas is None:
            return

        slices = split_image(np.asarray(canvas), 256, overlap=30)
        normalized = slices['image_batch'] / 255.0
        
        predictions = self.inference_service.predict_batch(normalized)
        pred = predictions.argmax(axis=3)[..., None]

        assembled = merge_imageset(pred, slices['assembly_pattern'], canvas.size, 30)
        
        self.save_as_geotiff(np.asarray(assembled), tile_dir, output_path)

    def save_as_geotiff(self, image: np.ndarray, tile_dir: Path, output_path: Path):
        tile_paths = [str(p) for p in tile_dir.glob('*.*')]
        
        # Используем оригинальный расчет bbox (Lat/Lon)
        bbox = get_bbox_for_tileset(tile_paths, z=17)
        
        transform = rasterio.transform.from_bounds(
            west=bbox['west'], 
            south=bbox['south'], 
            east=bbox['east'], 
            north=bbox['north'],
            width=image.shape[1],
            height=image.shape[0]
        )

        profile = {
            'driver': 'GTiff',
            'dtype': 'uint8',
            'nodata': None,  # <--- ВАЖНО: 0 это данные (Лес), а не пустота!
            'width': image.shape[1],
            'height': image.shape[0],
            'count': 1,
            'crs': rasterio.CRS.from_epsg(4326), # <--- Явно 4326
            'transform': transform,
            'compress': 'lzw'
        }

        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(image.astype('uint8'), 1)

def task_segmentate():
    task = SegmentationTask()
    task.run()

if __name__ == "__main__":
    task_segmentate()