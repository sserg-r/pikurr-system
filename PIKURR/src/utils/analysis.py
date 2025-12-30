import numpy as np
from typing import Optional

def calculate_usability_metric(arr: np.ndarray) -> Optional[np.ndarray]:
    """
    Вспомогательная функция для оценки используемости территории.
    Исходное название: is_using
    
    :param arr: Входной массив данных SCL в форме (Bands, Height, Width)
    :return: Массив оценок используемости в форме (Height, Width)
    """
    def _process_pixel(x: np.ndarray) -> int:
        """Обрабатывает временной ряд одного пикселя"""
        x = np.asarray(x)
        # Фильтруем значения SCL: берем только 4 (Vegetation) и 5 (Non-vegetated)
        filtered = x[(x > 3) & (x < 6)]
        
        if len(filtered) < 4:
            return 0
            
        kern1 = np.array([4, 4, 5, 5])
        kern2 = np.array([5, 5, 4, 4])
        
        # Корреляция с шаблонами
        k1 = np.correlate(filtered, 1/kern1, 'valid')
        k2 = np.correlate(filtered, 1/kern2, 'valid')
        
        return np.sum(k1 == 4) + np.sum(k2 == 4)

    if arr.size == 0:
        return None

    # Преобразуем массив к форме (Bands, Height*Width)
    b, h, w = arr.shape
    reshaped = arr.reshape(b, -1)
    
    # Применяем функцию к каждому пикселю
    result = np.apply_along_axis(_process_pixel, 0, reshaped)
    
    # Возвращаем к исходной форме (Height, Width)
    return result.reshape(h, w)