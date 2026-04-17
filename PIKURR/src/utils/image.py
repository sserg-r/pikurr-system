"""
Модуль обработки изображений: нарезка, склейка, работа с тайлами.
Восстановлена оригинальная логика PIKURR для сохранения геопривязки.
"""
import math
import numpy as np
from PIL import Image
from glob import glob
from pathlib import Path
from typing import Tuple, Dict, Union, List

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


def merge_tiles(tile_path: Union[str, Path]) -> Union[Image.Image, None]:
    """
    Склейка тайлов из папки.
    """
    path_str = str(tile_path)
    pathes = glob(path_str + '/*')
    if not pathes:
        return None

    # Оригинальная сортировка: x.split('_')[-1]+x.split('_')[-2]
    # Это сортировка строк. Чтобы избежать проблем с '10' < '2', лучше парсить в int.
    # Но сохраняем принцип: Сначала Y ([-1]), потом X ([-2]).
    def sort_key(x):
        stem = Path(x).stem # z_x_y
        parts = stem.split('_')
        if len(parts) >= 3:
            return int(parts[2]), int(parts[1]) # Y, X
        return 0, 0

    pathes.sort(key=sort_key)
    
    ima = []
    for p in pathes:
        try:
            with Image.open(p) as im:
                arr = np.asarray(im)
                if arr.ndim == 3 and arr.shape[2] >= 3:
                    ima.append(arr[:,:,:3])
                else:
                    ima.append(arr)
        except:
            continue

    if not ima:
        return None

    # Вычисление сетки
    # rows=len(set([p.split('_')[-2] for p in pathes])) -> Это подсчет уникальных X ?
    # Нет, [-2] это X в имени z_x_y. 
    # В оригинале: rows = len(set(X_indices)).
    # lines = total / rows. 
    # assembly_pattern передавался как (lines, rows). 
    # Значит (Количество Y, Количество X).
    
    x_indices = set()
    for p in pathes:
        parts = Path(p).stem.split('_')
        if len(parts) >= 2:
            x_indices.add(parts[1]) # X index
            
    rows_count = len(x_indices) # Это количество столбцов (Columns)
    if rows_count == 0: return None
    
    lines_count = len(pathes) // rows_count # Это количество строк (Rows)
    
    # В оригинале вызов: merge_imageset(..., (lines, rows), 0, 0)
    return merge_imageset(np.array(ima), (lines_count, rows_count), 0, margin=0)