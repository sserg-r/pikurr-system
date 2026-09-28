# -*- coding: utf-8 -*-
"""
round48, блок B1: замер "после" — те же операции, что в measure_speed.py
(код 1.1.0), но через РЕАЛЬНЫЙ код панели 1.2.0 (не переписанная копия
логики) — честное сравнение того, что действительно исполняется.

Запуск — как measure_speed.py.
"""
import os
import statistics
import sys
import time

try:
    import pikurr_qgis
    PLUGIN_DIR = pikurr_qgis.__path__[0]
except ImportError:
    PLUGIN_DIR = os.path.join(os.getcwd(), 'pikurr_qgis')
    sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from pikurr_qgis.pikurr import pikurr as PikurrPlugin  # noqa: E402
from pikurr_qgis import geoserver_client  # noqa: E402
from qgis.utils import iface  # noqa: E402

N_REPS = 3


def timed(fn, n=N_REPS):
    times = []
    for _ in range(n):
        t0 = time.time()
        fn()
        times.append(time.time() - t0)
    return times


def report(label, times):
    print(f'{label}: {[round(t, 3) for t in times]} с '
          f'(среднее {round(statistics.mean(times), 3)} с)', flush=True)


def main():
    print('=== round48 блок B1: замер "после" (код 1.2.0, панель) ===', flush=True)
    print(f'Машина: координаторская, точка входа: {geoserver_client.DEFAULT_GEOSERVER_URL}, '
          f'повторов: {N_REPS}\n', flush=True)

    plugin = PikurrPlugin(iface)
    plugin.initGui()
    plugin.toggle_panel()
    panel = plugin.panel

    distr_idx = next(i for i in range(panel.districtCombo.count())
                      if panel.districtCombo.itemData(i) == '2212')

    # "Открытие панели" — уже произошло один раз выше (toggle_panel вызвал
    # refresh_data). Замер "открытия" честно включает первый вызов —
    # B2.3 (загрузка один раз за сеанс) означает, что ПОВТОРНОЕ открытие
    # почти бесплатно (данные уже в памяти) — замеряем оба состояния.
    times_first_open = timed(lambda: plugin.refresh_data(force=True), n=N_REPS)
    report('Открытие панели (force=True, полный цикл сети каждый раз)', times_first_open)

    times_cached_open = timed(lambda: plugin.refresh_data(force=False), n=N_REPS)
    report('Повторное открытие панели (B2.3: данные уже загружены)', times_cached_open)

    def select_user():
        panel.districtCombo.setCurrentIndex(distr_idx)
        plugin._on_district_changed(distr_idx)
        user_idx = next(i for i in range(panel.userCombo.count())
                         if panel.userCombo.itemData(i) == '2212000055')
        panel.userCombo.setCurrentIndex(user_idx)
        plugin._on_user_changed(user_idx)

    times = timed(select_user)
    report('Выбор землепользователя 2212000055 (полный цикл: слой+границы+статистика)', times)

    def select_district():
        panel.districtCombo.setCurrentIndex(distr_idx)
        plugin._on_district_changed(distr_idx)

    times = timed(select_district)
    report('Весь район 2212 (полный цикл: слой+границы+статистика)', times)

    panel.aiCheckBox.setChecked(True)  # первый раз строит слой
    panel.aiCheckBox.setChecked(False)

    def toggle_ai():
        panel.aiCheckBox.setChecked(True)
        panel.aiCheckBox.setChecked(False)

    times = timed(toggle_ai)
    report('Переключение AI-оценки (WMTS/GWC, слой уже построен один раз)', times)

    # Отрисовка — те же bbox/протокол, что в measure_speed.py (before)
    from qgis.core import (QgsProject, QgsMapSettings, QgsMapRendererParallelJob,
                            QgsRectangle, QgsCoordinateReferenceSystem)
    from qgis.PyQt.QtCore import QSize

    bbox_district_2212 = QgsRectangle(3318534.208, 7341262.722, 3441208.287, 7478131.670)
    bbox_user = QgsRectangle(3401066.479, 7435968.408, 3401534.020, 7436732.611)

    def render(layer, bbox):
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(QgsCoordinateReferenceSystem(3857))
        settings.setExtent(bbox)
        settings.setOutputSize(QSize(1600, 900))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        return job.renderedImage()

    def nonempty_fraction(img):
        w, h = img.width(), img.height()
        nonempty = total = 0
        for y in range(0, h, max(1, h // 140)):
            for x in range(0, w, max(1, w // 140)):
                if (img.pixel(x, y) >> 24) & 0xFF > 0:
                    nonempty += 1
                total += 1
        return nonempty / total if total else 0

    panel.aiCheckBox.setChecked(True)
    raster_layer = QgsProject.instance().mapLayer(plugin._raster_layer_id)
    for label, bbox in (('охват района 2212', bbox_district_2212),
                        ('охват землепользователя 2212000055', bbox_user)):
        times = timed(lambda b=bbox: render(raster_layer, b))
        img = render(raster_layer, bbox)
        report(f'Отрисовка AI-оценки (WMTS) 1600x900, {label}', times)
        print(f'  доля непрозрачных пикселей: {nonempty_fraction(img):.1%}', flush=True)

    select_district()  # оставляет self._fields_layer_id заполненным
    fields_layer = QgsProject.instance().mapLayer(plugin._fields_layer_id)
    for label, bbox in (('охват района 2212', bbox_district_2212),
                        ('охват землепользователя 2212000055', bbox_user)):
        times = timed(lambda b=bbox: render(fields_layer, b))
        img = render(fields_layer, bbox)
        report(f'Отрисовка слоя полей (EPSG:3857) 1600x900, {label}', times)
        print(f'  доля непрозрачных пикселей: {nonempty_fraction(img):.1%}', flush=True)

    print('\n=== конец замера ===', flush=True)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    import os as _os
    _os._exit(2)
import os
os._exit(0)
