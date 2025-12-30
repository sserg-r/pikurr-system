import ee
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from google.oauth2.service_account import Credentials
from rasterio.io import MemoryFile
from typing import List, Dict, Union, Optional

from src.core.config import settings

class GEEService:
    def __init__(self):
        # Инициализация GEE через Service Account
        service_account_info = settings.gee.service_account
        
        credentials = Credentials.from_service_account_info(service_account_info)
        scoped_credentials = credentials.with_scopes(
            ['https://www.googleapis.com/auth/earthengine']
        )
        
        ee.Initialize(credentials=scoped_credentials)
        self.project = settings.gee.project

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=20))
    def get_scl_series_url(self, year: int, bbox: List[float]) -> Optional[str]:
        """
        Формирует временной ряд SCL (Scene Classification) и возвращает URL для скачивания.
        Алгоритм полностью повторяет логику оригинального geehandling.py.
        """
        aoi = ee.Geometry.BBox(*bbox)
        
        # 1. Проверка площади
        # В оригинале лимит 25 кв.км (25,000,000 м2)
        aoi_area = aoi.area(1).getInfo()
        if aoi_area > 25000000:
            raise ValueError(f'Area of AOI: {aoi_area} > 25000000 sq m')

        # 2. Настройка коллекций
        fdate = ee.Filter.date(f'{year}-04-15', f'{year}-10-15')
        cs_plus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
        s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')

        QA_BAND = 'cs_cdf'
        CLEAR_THRESHOLD = 0.80
        CPP = 20

        # Функция обновления SCL на основе Cloud Score+
        def update_scl(img):
            # Если качество (qa) низкое, ставим SCL=12 (невалидные данные?), иначе оставляем как есть
            scl = img.select('SCL').where(img.select(QA_BAND).lte(CLEAR_THRESHOLD), 12).rename('SCL')
            
            # В оригинале: return img.select(bandsToKeep).addBands(scl)
            # Но потом выбирается только SCL. Поэтому можно сразу вернуть только SCL.
            # Для точности воспроизведения оригинала:
            return img.addBands(scl, overwrite=True)

        # 3. Фильтрация и процессинг
        img_col = (s2.filterBounds(aoi)
                   .filter(fdate)
                   .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', CPP))
                   .linkCollection(cs_plus, [QA_BAND])
                   .map(update_scl))

        # 4. Группировка по дням (Mosaic)
        # Получаем список уникальных дней
        doi = img_col.toList(img_col.size()).map(lambda img: ee.Image(img).date().getRelative('day', 'year'))
        unique_doi = doi.distinct()

        def create_daily_mosaic(d):
            # Фильтруем снимки за конкретный день
            day_col = img_col.filter(ee.Filter.dayOfYear(d, ee.Number(d).add(1)))
            # mosaic() берет пиксели сверху вниз.
            # set metadata для сортировки
            return day_col.mosaic().set({
                'system:index': ee.String(d),
                'system:time_start': ee.Image(day_col.first()).get('system:time_start')
            })

        mosaic_col = ee.ImageCollection(unique_doi.map(create_daily_mosaic))

        # Если коллекция пустая, URL не получить
        if mosaic_col.size().getInfo() == 0:
            return None

        # 5. Преобразование в многоканальный имидж (toBands) и получение URL
        try:
            url = mosaic_col.select('SCL').sort('system:time_start').toBands().getDownloadURL({
                'scale': 10,
                'region': aoi,
                'crs': 'EPSG:4326',
                'filePerBand': False,
                'format': "GEO_TIFF"
            })
            return url
        except Exception as e:
            # GEE иногда выбрасывает ошибки при генерации URL для слишком больших/пустых данных
            print(f"GEE URL generation error: {e}")
            raise e

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=20))
    def download_gee_data(self, url: str) -> Dict:
        """
        Скачивает GeoTIFF по ссылке в память и возвращает данные + профиль.
        """
        response = requests.get(url, stream=True)
        if response.status_code != 200:
            response.raise_for_status()
            
        with MemoryFile(response.content) as memfile:
            with memfile.open() as dataset:
                # dataset.read() вернет массив (Bands, Height, Width)
                return {
                    'profile': dataset.profile,
                    'data': dataset.read()
                }