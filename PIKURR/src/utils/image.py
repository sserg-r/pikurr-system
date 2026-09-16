"""
Модуль обработки изображений: нарезка, склейка, работа с тайлами.
Восстановлена оригинальная логика PIKURR для сохранения геопривязки.
"""
import json
import logging
import math
import re
import numpy as np
from PIL import Image
from glob import glob
from pathlib import Path
from typing import Optional, Tuple, Dict, Union, List

logger = logging.getLogger(__name__)

# Имя тайла: {z}_{x}_{y}, расширение — из белого списка. Сетка в merge_tiles
# выводится из количества файлов, поэтому посторонний файл в папке листа
# (temp-файл, .DS_Store, служебный json и т.п.) молча портит lines_count и
# перекашивает склейку. См. prompts/PROMPT_dzz_export_round3.md, п.2.
_TILE_STEM_RE = re.compile(r'^\d+_\d+_\d+$')
_TILE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}

def split_image(img: np.ndarray, window_size: int = 256, overlap: int = 10) -> Dict:
    """
    Разрезка изображения на равные сегменты.
    Оригинальная логика PIKURR.
    """
    margin = overlap
    assert not margin % 2, 'margin must be even'
    
    # img.shape может быть (H, W, C) или (H, W)
    h, w = img.shape[0], img.shape[1]
    sh = [h, w]
    
    step = window_size - margin

    nrows = math.ceil(img.shape[0] / step)
    ncols = math.ceil(img.shape[1] / step)

    extended_im_size = [i * window_size - (i - 1) * margin for i in [nrows, ncols]]
    
    padx = extended_im_size[0] - sh[0]
    pady = extended_im_size[1] - sh[1]
    
    # Паддинг (reflection)
    if img.ndim == 3:
        pad_width = ((0, padx), (0, pady), (0, 0))
    else:
        pad_width = ((0, padx), (0, pady))
        
    img_ext = np.pad(img, pad_width, 'reflect')

    splitted = []
    # Важно: порядок циклов как в оригинале (rows, then cols)
    for i in range(nrows):
        for j in range(ncols):
            h_start = j * step
            v_start = i * step
            cropped = img_ext[v_start : v_start + window_size, h_start : h_start + window_size]
            splitted.append(cropped)
            
    return {'image_batch': np.array(splitted), 'assembly_pattern': (nrows, ncols)}


def merge_imageset(images: np.ndarray, assembly_pattern: Tuple[int, int], 
                  crop_size: Union[Tuple[int, int], int] = 0, margin: int = 10) -> Image.Image:
    """
    Функция объединения набора изображений в единое изображение.
    Оригинальная логика PIKURR.
    """
    if len(images) == 0:
        return None

    imsize = images[0].shape
    immode = 'RGB' if len(imsize) > 2 and imsize[-1] == 3 else 'L'

    # Решейп массива
    # assembly_pattern = (nrows, ncols)
    imarr = images.reshape((*assembly_pattern, *imsize))
    image_idx = assembly_pattern    
    
    # Создаем канвас
    canvas = Image.new(immode, (image_idx[1] * imsize[0], image_idx[0] * imsize[1]))
    
    shift = margin // 2    
    
    # Цикл по колонкам (i)
    for i in range(image_idx[1]):
        shy = 0 if i == 0 else shift
        # Цикл по строкам (j)
        for j in range(image_idx[0]):
            arr = imarr[j, i].astype(np.uint8)
            shx = 0 if j == 0 else shift           
            
            # Обрезка массива (slicing)
            if immode == 'RGB':
                arr = arr[shx:, shy:]
            else:
                # Обработка размерности для ч/б
                if arr.ndim == 3:
                    arr = arr[shx:, shy:, 0]
                else:
                    arr = arr[shx:, shy:]
            
            # Оригинальная формула расчета координат вставки
            x = i * 256 - (2 * i - 1) * shy
            y = j * 256 - (2 * j - 1) * shx
            
            im = Image.fromarray(arr, mode=immode)
            canvas.paste(im, (x, y))
    
    # Финальная обрезка (crop_size)
    # Оригинал: canvas.crop((0, 0, *crop_size)) - это работает, если crop_size tuple
    # if crop_size != 0:
    #     if isinstance(crop_size, (list, tuple)):
    #          canvas = canvas.crop((0, 0, crop_size[0], crop_size[1]))

    # Финальная обрезка (crop_size)
    # crop_size приходит как (Height, Width) из numpy.shape
    if crop_size != 0:
        if isinstance(crop_size, (list, tuple)):
             target_h = crop_size[0]
             target_w = crop_size[1]
             # PIL crop ожидает: (left, top, right, bottom) -> (0, 0, Width, Height)
             canvas = canvas.crop((0, 0, target_w, target_h))   
            
    return canvas


def merge_tiles(
    tile_path: Union[str, Path],
    gaps_out_path: Union[str, Path, None] = None,
    tile_range: Optional[Tuple[int, int, int, int]] = None,
) -> Union[Image.Image, None]:
    """
    Склейка тайлов из папки.

    Сетка сборки (число строк/столбцов) строится по **ожидаемому диапазону
    координат**, а не подсчётом числа файлов — раньше `rows_count =
    len(x_indices)` и `lines_count = len(pathes) // rows_count` выводились из
    того, что есть на диске, поэтому единичный пропавший тайл ломал
    целочисленное деление (`ValueError` при `reshape`), а пропажа целого
    X-столбца тихо съезжала сетку без единой ошибки (раунд 12, задача 4;
    раунд 13, задача 3). Недостающие ячейки заполняются чёрным плейсхолдером
    на своих истинных координатах, поэтому все последующие тайлы не
    сдвигаются. Математика самой склейки (`merge_imageset`) не менялась —
    здесь меняется только то, что в неё передаётся.

    `tile_range`, если задан, — `(min_x, max_x, min_y, max_y)` **истинной**
    границы листа (например, из геометрии `razgrafka`, а не из bbox
    присутствующих файлов). Без него диапазон по-прежнему выводится из
    присутствующих файлов — это оставляет прежнюю (раунд 13) уязвимость: если
    у листа отсутствуют тайлы **за пределами** bbox присутствующих файлов
    (не пропуск внутри, а целый неохваченный край — пример `O-35-142-В-б-3`,
    раунд 13/14), канвас соберётся только по видимой площади. Явный
    `tile_range` устраняет это полностью — регрессия раунда 13/14, задача 2.

    `gaps_out_path`, если задан, — куда написать `<лист>_gaps.json` со
    списком недостающих координат (по аналогии с `_missing.json` раунда 2,
    рядом с папкой листа, а не внутри неё). Файл пишется только если пропуски
    реально есть.
    """
    path_str = str(tile_path)
    pathes = [
        p for p in glob(path_str + '/*')
        if Path(p).suffix.lower() in _TILE_EXTENSIONS and _TILE_STEM_RE.match(Path(p).stem)
    ]
    if not pathes:
        return None

    # Индекс присутствующих тайлов по (x, y); z берём общий (в норме один на лист).
    present: Dict[Tuple[int, int], str] = {}
    z_val = None
    for p in pathes:
        stem = Path(p).stem  # z_x_y
        z_s, x_s, y_s = stem.split('_')
        z_i, x_i, y_i = int(z_s), int(x_s), int(y_s)
        present[(x_i, y_i)] = p
        z_val = z_i

    if tile_range is not None:
        min_x, max_x, min_y, max_y = tile_range
    else:
        xs = [c[0] for c in present]
        ys = [c[1] for c in present]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    cols = max_x - min_x + 1  # ожидаемое число X-столбцов
    rows = max_y - min_y + 1  # ожидаемое число Y-строк

    # Размер и число каналов тайла - по первому реально читаемому файлу.
    tile_hw = None
    channels = 1
    for p in present.values():
        try:
            with Image.open(p) as im:
                arr = np.asarray(im)
        except Exception:
            continue
        tile_hw = arr.shape[:2]
        channels = arr.shape[2] if arr.ndim == 3 else 1
        break
    if tile_hw is None:
        return None

    placeholder = (
        np.zeros((*tile_hw, channels), dtype=np.uint8) if channels > 1
        else np.zeros(tile_hw, dtype=np.uint8)
    )

    # Порядок как раньше: Y снаружи, X внутри (merge_imageset ждёт плоский
    # массив в порядке reshape((rows, cols, *imsize))).
    ima = []
    gaps = []
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            p = present.get((x, y))
            if p is None:
                ima.append(placeholder)
                gaps.append({"z": z_val, "x": x, "y": y, "reason": "no_tile_file"})
                continue
            try:
                with Image.open(p) as im:
                    arr = np.asarray(im)
                    if arr.ndim == 3 and arr.shape[2] >= 3:
                        arr = arr[:, :, :3]
            except Exception:
                arr = placeholder
                gaps.append({"z": z_val, "x": x, "y": y, "reason": "unreadable_tile_file"})
            ima.append(arr)

    if gaps and gaps_out_path is not None:
        expected = rows * cols
        payload = {
            "z": z_val, "min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y,
            "expected_tiles": expected, "missing_count": len(gaps),
            "missing_fraction": round(len(gaps) / expected, 4) if expected else 0.0,
            "missing": gaps,
        }
        try:
            with open(gaps_out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
        except OSError as e:
            logger.error(f"Не удалось записать {gaps_out_path}: {e}")

    return merge_imageset(np.array(ima), (rows, cols), 0, margin=0)