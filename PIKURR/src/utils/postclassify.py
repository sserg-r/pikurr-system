"""
Модуль для постклассификационных манипуляций над изображением
"""
import logging
import numpy as np
from skimage.morphology import closing, disk, erosion
import rasterio
from rasterio.features import sieve
from shapely.geometry import shape, mapping
from rasterio.merge import merge
import rasterio.mask
import json  # <--- ВАЖНО: Добавлен импорт

logger = logging.getLogger(__name__)

# ... (функция clean без изменений) ...
def clean(masked_image: np.ma.core.MaskedArray, closing_tr=2, sieve_tr=3) -> np.ma.core.MaskedArray:
    """
    Постклассификационная очистка изображения
    """
    im = masked_image
    footprint = disk(closing_tr)
    
    immask = erosion(im[0].mask, disk(1))
    
    # Приводим к int
    data_int = im[0].data.astype(int)
    mx = np.max(data_int) + 1
    imdata = (data_int * (-1) + mx)
    
    outmask = np.copy(imdata)
    imdata[immask] = -1
    
    lbls = np.unique(imdata)
    lbls = lbls[lbls != -1]

    for lbl in lbls:
        imm = np.copy(imdata)
        imm[imm != lbl] = 0
        imm[immask] = lbl
        imm = closing(imm, footprint)
        
        mask_not_lbl = (imm != lbl)
        imm[mask_not_lbl] = imdata[mask_not_lbl]
        imdata = imm
        
    imdata[immask] = outmask[immask]
    
    # image_result = sieve(imdata.astype(rasterio.int32), sieve_tr, out=None, connectivity=4)
    image_result = sieve(imdata.astype(np.int32), size=sieve_tr, connectivity=4)
    
    return np.ma.masked_array(image_result * (-1) + mx, immask)


def sanitize_coords(coords):
    """Рекурсивно превращает кортежи в списки для совместимости с GeoJSON"""
    if isinstance(coords, (list, tuple)):
        return [sanitize_coords(x) for x in coords]
    return coords

def calculate_zonal_stats(geom_input, tiff_paths: list) -> dict:
    # 1. ПАРСИНГ ГЕОМЕТРИИ
    try:
        if isinstance(geom_input, str):
            geometry_dict = json.loads(geom_input)
        elif isinstance(geom_input, dict):
            geometry_dict = geom_input
        else:
            # Fallback
            from shapely.geometry import mapping
            geometry_dict = mapping(geom_input)
            # Принудительная очистка через JSON цикл
            geometry_dict = json.loads(json.dumps(geometry_dict))
            
        shapes = [geometry_dict]
        
    except Exception as e:
        logger.error(f"Geometry parsing error: {e}")
        return {}

    srcs = [rasterio.open(f) for f in tiff_paths]
    if not srcs:
        return {}

    meta = srcs[0].meta
    data, transform = merge(srcs, nodata=255)
    meta.update(transform=transform, width=data.shape[2], height=data.shape[1], nodata=255)
    [src.close() for src in srcs]

    from rasterio.io import MemoryFile
    with MemoryFile() as memfile:
        with memfile.open(**meta) as src:
            src.write(data)
            
            # --- БЛОК ГЛУБОКОЙ ОТЛАДКИ ---
            # Проверяем то, на что ругается Rasterio, ПЕРЕД вызовом
            check_failed = False
            if not isinstance(shapes, list):
                logger.error(f"[DEBUG_FAIL] 'shapes' is not a list! Type: {type(shapes)}")
                check_failed = True
            elif len(shapes) == 0:
                logger.error(f"[DEBUG_FAIL] 'shapes' is empty!")
                check_failed = True
            else:
                item = shapes[0]
                if not isinstance(item, dict):
                    logger.error(f"[DEBUG_FAIL] Item is not a dict! Type: {type(item)}")
                    logger.error(f"[DEBUG_FAIL] Value: {item}")
                    check_failed = True
                else:
                    # Проверяем структуру GeoJSON
                    if 'type' not in item or 'coordinates' not in item:
                        logger.error(f"[DEBUG_FAIL] Dict is missing GeoJSON keys: {item.keys()}")
            
            if check_failed:
                logger.error("Aborting before rasterio crash.")
                return {}
            # -----------------------------

            try:
                out_image, out_transform = rasterio.mask.mask(
                    src, shapes, crop=True, filled=False, pad=True, pad_width=2, nodata=255
                )
            except Exception as e:
                # Если упало здесь, значит проверка выше прошла, но rasterio все равно недоволен
                logger.error(f"--- RASTERIO CRASH DUMP ---")
                logger.error(f"Rasterio version: {rasterio.__version__}")
                logger.error(f"Error: {e}")
                logger.error(f"Shapes dump (first 200 chars): {str(shapes)[:200]}")
                # Выводим тип координат (это частая проблема)
                try:
                    coords = shapes[0]['coordinates']
                    logger.error(f"Coords type: {type(coords)}")
                    if len(coords) > 0:
                         logger.error(f"First ring type: {type(coords[0])}")
                         if len(coords[0]) > 0:
                             logger.error(f"First point type: {type(coords[0][0])} -> {coords[0][0]}")
                except:
                    pass
                logger.error(f"---------------------------")
                raise e

    cleaned = clean(out_image)

    unique, counts = np.unique(cleaned, return_counts=True)
    if hasattr(unique, 'mask'):
        mask = unique.mask
        unique = unique.data[~mask]
        counts = counts[~mask]

    valid_indices = unique != 255
    unique = unique[valid_indices]
    counts = counts[valid_indices]

    total = np.sum(counts)
    if total == 0:
        return {}

    percentages = counts / total
    return {str(int(k)): float(v) for k, v in zip(unique, percentages)}