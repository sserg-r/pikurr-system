# Общая часть скриптов раунда 56 (запуск: docker exec -i pikurr-system-etl-1 python3 - < (lib.py + скрипт)).
# Только чтение: БД (SELECT), каталоги данных (open 'r'), результат — в stdout.
import sys, json, math, glob, os, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, '/app')
import numpy as np, rasterio
from rasterio.features import geometry_mask
from shapely import wkt as _wkt
from shapely.geometry import box
import shapely
FINAL = '/data_output/predictions/predictions_final/2025'
VEGET = '/data_output/predictions/predictions_veget'
USAB = '/data_output/predictions/predictions_usab'
PUBLIC = '/data_output/predictions/geoserver_public/2025'
Z = 17
_a = 6378137.0; _f = 1/298.257223563; _e2 = _f*(2-_f); _e = math.sqrt(_e2)
def _q(phi):
    s = np.sin(phi)
    return (1-_e2)*(s/(1-_e2*s*s) - (1/(2*_e))*np.log((1-_e*s)/(1+_e*s)))
def ea(geom):
    """Геометрия lon/lat -> эквивалентная по площади проекция на эллипсоиде (метры)."""
    return shapely.transform(geom, lambda c: np.column_stack([np.radians(c[:,0])*_a, _a*_q(np.radians(c[:,1]))/2]))
def area_ha(geom):
    return ea(geom).area/10000.0
def sheets():
    from src.services.db import DatabaseService
    from src.core.config import settings
    df = DatabaseService(settings).execute_query("select n10000, ST_AsText(geom) g from razgrafka")
    return {r.n10000: _wkt.loads(r.g) for r in df.itertuples()}
def raster_files():
    return {os.path.splitext(os.path.basename(p))[0]: p for p in sorted(glob.glob(FINAL + '/*.tif'))}
def tile_origin(src):
    """Глобальные пиксельные координаты z17 левого верхнего угла растра (целые)."""
    t = src.transform
    x0 = (t.c + 180.0)/360.0*(2**Z)*256
    lat = math.radians(t.f)
    y0 = (1 - math.asinh(math.tan(lat))/math.pi)/2*(2**Z)*256
    return round(x0), round(y0), x0, y0
