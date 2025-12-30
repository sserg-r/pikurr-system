import time
import logging
from src.core.config import settings
from src.tasks.initialize import InitializeTask
from src.tasks.download import DownloadTilesTask
from src.tasks.segmentate import SegmentationTask
from src.tasks.usability import UsabilityTask
from src.tasks.classify import ClassificationTask
from src.tasks.save_db import SaveStatsTask
from src.tasks.export import ExportTask
from src.tasks.package import PackageTask

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PIKURR_PIPELINE")

def main():
    logger.info("=== ЗАПУСК PIKURR ETL PIPELINE ===")
    
    # Небольшая задержка, чтобы БД точно успела инициализироваться
    # (хотя depends_on healthcheck должен помочь, но для надежности)
    time.sleep(2)

    try:
        # 1. Инициализация (Загрузка GeoJSON/Shapefiles в PostGIS)
        logger.info("[STEP 1/8] Initialization...")
        # InitializeTask в __init__ принимает settings
        InitializeTask(settings).run()
        
        # 2. Загрузка тайлов
        logger.info("[STEP 2/8] Downloading Tiles...")
        DownloadTilesTask(settings).run()
        
        # 3. Сегментация (TF Serving)
        logger.info("[STEP 3/8] Segmentation...")
        SegmentationTask().run()
        
        # 4. Usability (GEE)
        logger.info("[STEP 4/8] Usability Analysis...")
        UsabilityTask().run()
        
        # 5. Классификация (Морфология)
        logger.info("[STEP 5/8] Classification...")
        ClassificationTask().run()
        
        # 6. Сохранение статистики
        logger.info("[STEP 6/8] Saving Stats to DB...")
        SaveStatsTask().run()
        
        # 7. Подготовка растров для публикации
        logger.info("[STEP 7/8] Exporting Public Data...")
        ExportTask().run()

        # 8. Архивация данныхи
        logger.info("[STEP 8/8] Packaging Public Data...")
        PackageTask().run()

        logger.info("=== PIPELINE ЗАВЕРШЕН УСПЕШНО ===")

    except Exception as e:
        logger.error(f"CRITICAL ERROR IN PIPELINE: {e}")
        import traceback
        traceback.print_exc()
        # Не выходим сразу, чтобы контейнер не падал и можно было почитать логи
        time.sleep(600)

if __name__ == "__main__":
    main()