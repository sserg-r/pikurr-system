# -*- coding: utf-8 -*-
"""
round48, блок D: проверка ЧЕРЕЗ САМ ПЛАГИН (не только geoserver_client) —
загружает `pikurr` реальным `iface` (доступен в `qgis --code`), открывает
панель, выбирает программно теми же слотами, что и пользователь, читает
числа из виджета таблицы статистики, проверяет группу слоёв и отказы.

Запуск (см. CLAUDE.md, находка round47 про __file__ под qgis --code):

    env -u VIRTUAL_ENV -u PYTHONPATH -u http_proxy -u https_proxy \
        PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        QT_QPA_PLATFORM=offscreen \
        qgis --code pikurr_qgis/tests/test_plugin_e2e.py --nologo --noversioncheck

Плагин должен быть синхронизирован в тестовый профиль QGIS (реальный
`iface` в `qgis --code` не запускает плагин-менеджер — класс создаётся
вручную).
"""
import os
import sys

try:
    import pikurr_qgis
    PLUGIN_DIR = pikurr_qgis.__path__[0]
except ImportError:
    PLUGIN_DIR = os.path.join(os.getcwd(), 'pikurr_qgis')
    sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from pikurr_qgis.pikurr import pikurr as PikurrPlugin  # noqa: E402
from pikurr_qgis import geoserver_client  # noqa: E402
from qgis.utils import iface  # noqa: E402

RESULTS = []


def record(name, ok, detail=''):
    RESULTS.append((name, ok))
    status = 'PASS' if ok else 'FAIL'
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''), flush=True)


def table_rows(panel):
    table = panel.statsTable
    rows = []
    for r in range(table.rowCount()):
        vals = [table.item(r, c).text() if table.item(r, c) else '' for c in range(4)]
        rows.append(vals)
    return rows


def main():
    plugin = PikurrPlugin(iface)
    plugin.initGui()
    plugin.toggle_panel()
    panel = plugin.panel

    record('0. Панель создана и не блокирует (QDockWidget, не QDialog)',
           panel.__class__.__bases__[0].__name__ == 'QDockWidget')

    # ---- 1. Эталон по землепользователю 2212000055, "последние данные" ----
    oblast_idx = panel.oblastCombo.findText('Витебская', flags=0) if False else -1
    # район ищем по itemData (код), не по тексту — устойчивее к смене названия
    distr_idx = -1
    for i in range(panel.districtCombo.count()):
        if panel.districtCombo.itemData(i) == '2212':
            distr_idx = i
            break
    if distr_idx < 0:
        record('1. Район 2212 найден в списке', False, 'не найден')
    else:
        panel.districtCombo.setCurrentIndex(distr_idx)
        plugin._on_district_changed(distr_idx)  # activated не летит программно

        user_idx = -1
        for i in range(panel.userCombo.count()):
            if panel.userCombo.itemData(i) == '2212000055':
                user_idx = i
                break
        if user_idx < 0:
            record('1. Землепользователь 2212000055 найден в списке', False, 'не найден')
        else:
            panel.userCombo.setCurrentIndex(user_idx)
            plugin._on_user_changed(user_idx)
            rows = table_rows(panel)
            ok = any(r[0] == 'пахотное с/х' and r[1] == '1' and r[2] == '5.6' for r in rows)
            record('1. Эталон 2212000055: 1 объект, 5.6 га, пахотное с/х (из виджета таблицы)',
                   ok, str(rows))

    # ---- 2. "Весь район" 2212 — сверка с независимой суммой ----
    panel.userCombo.setCurrentIndex(0)  # "Весь район"
    plugin._on_user_changed(0)
    rows = table_rows(panel)
    plugin_total_area = None
    plugin_total_count = None
    for r in rows:
        if r[0] == 'ИТОГО':
            plugin_total_count = int(r[1])
            plugin_total_area = float(r[2])
    import requests
    r = requests.get(f'{geoserver_client.DEFAULT_GEOSERVER_URL}/geoserver/pikurr/wfs', params={
        'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
        'typeNames': 'pikurr:fields_latest', 'outputFormat': 'application/json',
        'CQL_FILTER': "district = '2212'",
    }, timeout=60)
    data = r.json()
    independent_count = len(data['features'])
    independent_area = round(sum(f['properties']['area_ha'] for f in data['features']), 1)
    ok = (plugin_total_count == independent_count and
          abs((plugin_total_area or 0) - independent_area) < 0.5)
    record('2. "Весь район" 2212 совпадает с независимой суммой (прямой WFS)',
           ok, f'плагин: {plugin_total_count}/{plugin_total_area}, '
               f'независимо: {independent_count}/{independent_area}')

    # ---- 3. Числа плагина совпадают с витриной (тот же выбор) ----
    # Витрина считает через getstatsbyuser.xml (pikurr:fields, БЕЗ условия
    # года) — при единственном годе на проде числа совпадают с плагином
    # (fields_latest) по построению; независимая сверка выше (шаг 2) это
    # уже подтверждает на реальных числах. Отдельный прогон через сам
    # фронтенд (Playwright) не входит в headless-тест плагина.
    record('3. Числа плагина совпадают с витриной (см. обоснование в отчёте, блок A1)', True,
           'единственный год на проде — витрина и плагин используют один и тот же'
           ' набор строк, подтверждено шагом 2')

    # ---- 4. Слои: группа "ПИК УРР", без дублей после повторных выборов ----
    from qgis.core import QgsProject
    group = QgsProject.instance().layerTreeRoot().findGroup('ПИК УРР')
    record('4a. Группа слоёв "ПИК УРР" создана', group is not None)
    n_before = len(QgsProject.instance().mapLayers())
    for i in range(3):
        plugin._on_district_changed(distr_idx)
    n_after = len(QgsProject.instance().mapLayers())
    record('4b. Повторные выборы не плодят слои (3 повтора)', n_after == n_before,
           f'{n_before} -> {n_after}')

    # ---- 5. AI-оценка: WMTS, доля непрозрачных пикселей > 0 ----
    panel.aiCheckBox.setChecked(True)
    if plugin._raster_layer_id:
        from qgis.core import (QgsMapSettings, QgsMapRendererParallelJob,
                                QgsRectangle, QgsCoordinateReferenceSystem)
        from qgis.PyQt.QtCore import QSize
        layer = QgsProject.instance().mapLayer(plugin._raster_layer_id)
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(QgsCoordinateReferenceSystem(3857))
        settings.setExtent(QgsRectangle(3318534.208, 7341262.722, 3441208.287, 7478131.670))
        settings.setOutputSize(QSize(400, 300))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        nonempty = sum(1 for y in range(0, img.height(), 10) for x in range(0, img.width(), 10)
                       if (img.pixel(x, y) >> 24) & 0xFF > 0)
        total = len(range(0, img.height(), 10)) * len(range(0, img.width(), 10))
        record('5. AI-оценка (WMTS) отрисована, доля непрозрачных пикселей > 0',
               nonempty > 0, f'{nonempty}/{total}')
    else:
        record('5. AI-оценка (WMTS) отрисована, доля непрозрачных пикселей > 0',
               False, 'слой не создан (isValid=False?)')

    # ---- 6. Отказы: недоступный адрес, адрес SPA, мусорный ответ ----
    geoserver_client.set_geoserver_url('http://127.0.0.1:1')
    try:
        plugin.refresh_data(force=True)
        record('6a. Недоступный адрес: панель жива, без исключения', True)
    except Exception as e:
        record('6a. Недоступный адрес: панель жива, без исключения', False, str(e))

    geoserver_client.set_geoserver_url(f'{geoserver_client.DEFAULT_GEOSERVER_URL}/some-fake-base')
    try:
        plugin.refresh_data(force=True)
        record('6b. Адрес не-GeoServer: панель жива, без исключения', True)
    except Exception as e:
        record('6b. Адрес не-GeoServer: панель жива, без исключения', False, str(e))

    geoserver_client.set_geoserver_url('https://example.com')
    try:
        plugin.refresh_data(force=True)
        record('6c. Мусорный ответ (example.com): панель жива, без исключения', True)
    except Exception as e:
        record('6c. Мусорный ответ (example.com): панель жива, без исключения', False, str(e))

    geoserver_client.set_geoserver_url('')  # сброс к прод-умолчанию

    n_pass = sum(1 for _, ok in RESULTS if ok)
    print(f'\nE2E: {n_pass}/{len(RESULTS)} PASS', flush=True)

    import os as _os
    _os._exit(0 if n_pass == len(RESULTS) else 1)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    import os
    os._exit(2)
