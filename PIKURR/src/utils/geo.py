"""
Модуль гео-математических вычислений для работы с тайлами
"""

from math import pi, exp, tan, atan, cos, log
from typing import Tuple, Dict, List, Any
import re
import json
from pathlib import Path

def getTileIndex(lat: float, lon: float, zoomLevel: int) -> Tuple[int, int, int, int]:
    """
    Рассчет индекса тайла по координатам WGS84

    Args:
        lat: Широта в градусах
        lon: Долгота в градусах
        zoomLevel: Уровень масштабирования

    Returns:
        Кортеж (x, y, xpx, ypx) - индексы тайла и позиция внутри тайла
    """
    z = int(zoomLevel)
    xyTilesCount = 2**z
    x = int((lon + 180.0) / 360.0 * xyTilesCount)
    y = int((1.0 - log(tan(lat * pi / 180.0) + 1.0 / cos(lat * pi / 180.0)) / pi) / 2.0 * xyTilesCount)

    lon1 = x / 2**z * 360.0 - 180.0
    n1 = pi - 2.0 * pi * y / 2**z
    lat1 = 180.0 / pi * atan(0.5 * (exp(n1) - exp(-n1)))
    lon2 = (x + 1) / 2**z * 360.0 - 180.0
    n2 = pi - 2.0 * pi * (y + 1) / 2**z
    lat2 = 180.0 / pi * atan(0.5 * (exp(n2) - exp(-n2)))

    ypx = int((lon - lon1) / (lon2 - lon1) * 255)
    xpx = int((lat1 - lat) / (lat1 - lat2) * 255)

    return x, y, xpx, ypx

def tileZXYToLatLonBBox(zoomLevel: int, x: int, y: int) -> Dict[str, Any]:
    """
    Преобразование индексов тайла в географические координаты bbox

    Args:
        zoomLevel: Уровень масштабирования
        x: Индекс тайла по X
        y: Индекс тайла по Y

    Returns:
        GeoJSON-подобный словарь с координатами полигона
    """
    z = zoomLevel
    lon1 = x / 2**z * 360.0 - 180.0
    n1 = pi - 2.0 * pi * y / 2**z
    lat1 = 180.0 / pi * atan(0.5 * (exp(n1) - exp(-n1)))
    lon2 = (x + 1) / 2**z * 360.0 - 180.0
    n2 = pi - 2.0 * pi * (y + 1) / 2**z
    lat2 = 180.0 / pi * atan(0.5 * (exp(n2) - exp(-n2)))

    return {
        "type": "Feature",
        "properties": {"x": x, "y": y, "z": z},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lon1, lat1],
                [lon1, lat2],
                [lon2, lat2],
                [lon2, lat1],
                [lon1, lat1]
            ]]
        }
    }

def get_bbox_for_tileset(tileids: List[str], z: int = 17) -> Dict[str, float]:
    """
    Определение граничной рамки для набора тайлов.
    Ожидается формат имени файла: z_x_y.jpg (или png)
    """
    if not tileids:
        raise ValueError("Tile list is empty")

    x_coords = []
    y_coords = []

    for s in tileids:
        # Используем pathlib для надежного получения имени без пути и расширения
        # s = '/path/to/17_76798_43993.jpg' -> stem = '17_76798_43993'
        stem = Path(s).stem
        parts = stem.split('_')
        
        # Ожидаем формат [z, x, y]
        if len(parts) >= 3:
            x_coords.append(int(parts[1]))
            y_coords.append(int(parts[2]))
    
    if not x_coords:
        raise ValueError(f"Could not parse tile coordinates from filenames (Example: {tileids[0]})")

    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)

    # Получаем координаты верхнего левого угла самого левого-верхнего тайла
    # (min_x, min_y) -> Northwest corner
    ul_bbox = tileZXYToLatLonBBox(z, min_x, min_y)
    ul_coords = ul_bbox["geometry"]["coordinates"][0]
    # В полигоне тайла: [lon1, lat1], [lon1, lat2]... 
    # Нам нужны максимальные границы.
    # lat1 (верхняя граница) - это max(lats)
    # lon1 (левая граница) - это min(lons)
    
    # Получаем координаты нижнего правого угла самого правого-нижнего тайла
    # (max_x, max_y) -> Southeast corner
    dr_bbox = tileZXYToLatLonBBox(z, max_x, max_y)
    dr_coords = dr_bbox["geometry"]["coordinates"][0]
    
    # Собираем все координаты двух угловых тайлов, чтобы найти экстремумы
    all_lons = [p[0] for p in ul_coords] + [p[0] for p in dr_coords]
    all_lats = [p[1] for p in ul_coords] + [p[1] for p in dr_coords]

    return {
        "west": min(all_lons),
        "south": min(all_lats),
        "east": max(all_lons),
        "north": max(all_lats)
    }

def get_bbox_for_tileset_mercator(tileids: List[str], z: int = 17) -> Dict[str, float]:
    """
    Возвращает границы набора тайлов в метрах проекции Web Mercator (EPSG:3857).
    """
    if not tileids:
        raise ValueError("Tile list is empty")

    x_coords = []
    y_coords = []

    for s in tileids:
        stem = Path(s).stem
        parts = stem.split('_')
        if len(parts) >= 3:
            x_coords.append(int(parts[1]))
            y_coords.append(int(parts[2]))
    
    if not x_coords:
        raise ValueError("Could not parse coordinates")

    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)

    # Константы Web Mercator
    EARTH_RADIUS = 6378137.0
    ORIGIN_SHIFT = 2 * pi * EARTH_RADIUS / 2.0
    
    # Разрешение (метров на пиксель) на уровне зума 0
    INITIAL_RESOLUTION = 2 * pi * EARTH_RADIUS / 256.0
    
    # Разрешение тайла (ширина тайла в метрах) на текущем зуме
    # width_in_meters = resolution * 256
    resolution = INITIAL_RESOLUTION / (2**z)
    tile_size_meters = resolution * 256.0

    # Расчет координат
    # X растет слева направо. Origin (-20037508.34, 0)
    # min_x * tile_size -> левая граница самого левого тайла
    west = -ORIGIN_SHIFT + (min_x * tile_size_meters)
    
    # (max_x + 1) -> правая граница самого правого тайла
    east = -ORIGIN_SHIFT + ((max_x + 1) * tile_size_meters)

    # Y растет сверху вниз (в индексах тайлов), но снизу вверх в координатах (Meters)
    # Origin Y (+20037508.34) это верх карты
    # min_y -> самый верхний тайл. Его верхняя граница:
    north = ORIGIN_SHIFT - (min_y * tile_size_meters)
    
    # max_y -> самый нижний тайл. Его нижняя граница:
    south = ORIGIN_SHIFT - ((max_y + 1) * tile_size_meters)

    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north
    }