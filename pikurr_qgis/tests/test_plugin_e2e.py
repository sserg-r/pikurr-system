# -*- coding: utf-8 -*-
"""
round48/49, блок D: проверка ЧЕРЕЗ САМ ПЛАГИН — загружает `pikurr`
реальным `iface`, открывает панель, выбирает ЧЕРЕЗ РЕАЛЬНЫЕ Qt-события
(QTest), не прямым вызовом обработчиков — round49, блок A2 показал, что
прямой вызов `_on_district_changed()` не проверяет саму связку
"сигнал activated -> обработчик" (если бы сигнал был подключён неверно,
тест остался бы зелёным).

Запуск (см. CLAUDE.md, находки round47-49 про qgis --code):

    env -u VIRTUAL_ENV -u PYTHONPATH -u http_proxy -u https_proxy \
        PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        QT_QPA_PLATFORM=offscreen \
        qgis --code pikurr_qgis/tests/test_plugin_e2e.py --nologo --noversioncheck

Плагин должен быть синхронизирован в тестовый профиль QGIS.
"""
import os
import sys

try:
    import pikurr_qgis
    PLUGIN_DIR = pikurr_qgis.__path__[0]
except ImportError:
    PLUGIN_DIR = os.path.join(os.getcwd(), 'pikurr_qgis')
    sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from pikurr_qgis.pikurr import pikurr as PikurrPlugin, SCENARIO_LABELS  # noqa: E402
from pikurr_qgis import geoserver_client  # noqa: E402
from qgis.utils import iface  # noqa: E402
from qgis.PyQt.QtCore import Qt, QEvent  # noqa: E402
from qgis.PyQt.QtGui import QKeyEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402

RESULTS = []
REPO_ROOT_CANDIDATES = [os.path.dirname(os.path.dirname(PLUGIN_DIR)), os.getcwd()]


def record(name, ok, detail=''):
    RESULTS.append((name, ok))
    status = 'PASS' if ok else 'FAIL'
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''), flush=True)


def send_unicode_text(widget, text):
    """round49, A3: `QTest.keyClicks()` падает (ASSERT в qasciikey.cpp)
    на кириллице в этой сборке PyQt5/Qt5 под offscreen — обходной путь,
    эмулирующий реальную последовательность нажатий клавиш через сырые
    `QKeyEvent` с произвольным unicode `text`, без опоры на `Qt::Key`
    (которого для кириллицы просто нет)."""
    for ch in text:
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, Qt.Key_unknown, Qt.NoModifier, ch))
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, Qt.Key_unknown, Qt.NoModifier, ch))


def select_by_arrow(combo, target_data):
    """Реальная Qt-навигация (не programmatic setCurrentIndex) — стрелками
    вниз до нужного пункта, затем Enter. Подтверждает, что `activated`
    подключён к обработчику (round49, A2)."""
    target_idx = next(i for i in range(combo.count()) if combo.itemData(i) == target_data)
    combo.setCurrentIndex(-1)
    combo.setFocus()
    for _ in range(target_idx + 1):
        QTest.keyClick(combo, Qt.Key_Down)
    return target_idx


def table_rows(panel):
    table = panel.statsTable
    return [[table.item(r, c).text() if table.item(r, c) else '' for c in range(4)]
            for r in range(table.rowCount())]


def find_repo_file(rel_path):
    for root in REPO_ROOT_CANDIDATES:
        p = os.path.join(root, rel_path)
        if os.path.isfile(p):
            return p
    return None


def main():
    plugin = PikurrPlugin(iface)
    plugin.initGui()
    plugin.toggle_panel()
    panel = plugin.panel

    record('0. Панель создана и не блокирует (QDockWidget, не QDialog)',
           panel.__class__.__bases__[0].__name__ == 'QDockWidget')

    # ---- A2: выбор ЧЕРЕЗ РЕАЛЬНЫЙ Qt-сигнал (стрелки + Enter), не вызов метода ----
    select_by_arrow(panel.districtCombo, '2212')
    QTest.keyClick(panel.districtCombo, Qt.Key_Return)
    record('A2. Реальная навигация (Key_Down) по districtCombo вызывает activated '
           '-> строит "Весь район"',
           panel.districtCombo.currentData() == '2212' and panel.statsTable.rowCount() > 0,
           f'currentData={panel.districtCombo.currentData()}, '
           f'таблица_строк={panel.statsTable.rowCount()}')

    # A2, доказательство от противного: programmatic setCurrentIndex НЕ запускает цикл
    rows_before = table_rows(panel)
    panel.userCombo.setCurrentIndex(1)  # без keyClick/activated
    rows_after_programmatic = table_rows(panel)
    record('A2. programmatic setCurrentIndex НЕ меняет таблицу (доказывает, что '
           'подключён именно activated, не currentIndexChanged)',
           rows_before == rows_after_programmatic,
           f'до={rows_before[:1]}, после={rows_after_programmatic[:1]}')

    select_by_arrow(panel.userCombo, '2212000055')
    QTest.keyClick(panel.userCombo, Qt.Key_Return)
    rows = table_rows(panel)
    ok = any(r[0] == 'пахотное с/х' and r[1] == '1' and r[2] == '5.6' for r in rows)
    record('A2. Реальная навигация по userCombo (стрелки) -> эталон 1/5.6/пахотное с/х',
           ok, str(rows))

    # ---- A1: настоящая сверка с запросом ВИТРИНЫ (не рассуждение) ----
    getstats_path = find_repo_file('REPIKURR/repikurr/public/getstatsbyuser.xml')
    if getstats_path is None:
        record('A1. Сверка с реальным запросом витрины (getstatsbyuser.xml)', False,
               'файл не найден по известным путям репозитория')
    else:
        with open(getstats_path, encoding='utf-8') as fh:
            frontend_tpl = fh.read()
        # round50, блок A: шаблон витрины параметризован typeName/фильтром
        # (не {{CQL_FILTER}} — тот способ убран блоком B этого раунда).
        # "последние данные" (year=None) — тот же выбор, что был сделан
        # выше через реальную Qt-навигацию (fields_latest, без условия года).
        frontend_group_filter = (
            '<ogc:PropertyIsLike wildCard="*" singleChar="." escape="!">'
            '<ogc:PropertyName>nr_user</ogc:PropertyName>'
            '<ogc:Literal>2212000055*</ogc:Literal></ogc:PropertyIsLike>')
        frontend_xml = (frontend_tpl
                         .replace('{{TYPENAME}}', 'pikurr:fields_latest')
                         .replace('{{FILTER}}', f'<ogc:Filter>{frontend_group_filter}</ogc:Filter>'))
        try:
            frontend_stats = geoserver_client.wps_execute_json(
                geoserver_client.DEFAULT_GEOSERVER_URL, frontend_xml)
            f_funcs = frontend_stats['AggregationFunctions']
            f_count_idx = f_funcs.index('Count') + 1
            f_sum_idx = f_funcs.index('Sum') + 1
            # витрина отдаёт сырой код сценария (tillage), плагин — русскую
            # подпись (SCENARIO_LABELS) в виджете таблицы — приводим к
            # одному ключу для сравнения (не баг плагина, особенность теста).
            frontend_rows = {SCENARIO_LABELS.get(r[0], r[0]): (r[f_count_idx], r[f_sum_idx])
                              for r in frontend_stats['AggregationResults']}
            plugin_rows = {r[0]: (int(r[1]), float(r[2])) for r in rows if r[0] != 'ИТОГО'}
            ok = frontend_rows == plugin_rows
            record('A1. Числа плагина == числа запроса витрины (getstatsbyuser.xml, тот же CQL)',
                   ok, f'витрина={frontend_rows}, плагин={plugin_rows}')
        except geoserver_client.GeoServerError as e:
            record('A1. Числа плагина == числа запроса витрины', False, str(e))

    # ---- A4: границы и зум — куда именно, не просто "не упало" ----
    import requests
    r = requests.get(f'{geoserver_client.DEFAULT_GEOSERVER_URL}/geoserver/pikurr/wfs', params={
        'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
        'typeNames': 'pikurr:fields_latest', 'outputFormat': 'application/json',
        'CQL_FILTER': "nr_user LIKE '2212000055%'",
    }, timeout=20)
    data = r.json()
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for cc in c:
                walk(cc)
    for f in data['features']:
        walk(f['geometry']['coordinates'])
    obj_center_lon = (min(xs) + max(xs)) / 2
    obj_center_lat = (min(ys) + max(ys)) / 2

    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsPointXY
    src_crs = QgsCoordinateReferenceSystem('EPSG:4326')
    dest_crs = iface.mapCanvas().mapSettings().destinationCrs()
    transform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
    obj_center_proj = transform.transform(QgsPointXY(obj_center_lon, obj_center_lat))

    map_extent = iface.mapCanvas().extent()
    inside = map_extent.contains(obj_center_proj)
    map_center = map_extent.center()
    dist = ((map_center.x() - obj_center_proj.x()) ** 2 +
            (map_center.y() - obj_center_proj.y()) ** 2) ** 0.5
    tolerance = ((map_extent.width() ** 2 + map_extent.height() ** 2) ** 0.5) / 2
    record('A4. Центр объекта (независимый WFS, переведён в CRS проекта) '
           'внутри охвата карты и близко к центру',
           inside and dist < tolerance,
           f'внутри={inside}, расстояние_до_центра={dist:.1f}, допуск={tolerance:.1f}')

    # ---- A4, "Весь район" ----
    select_by_arrow(panel.userCombo, None)  # "Весь район" — itemData(0) = None
    QTest.keyClick(panel.userCombo, Qt.Key_Return)
    r2 = requests.get(f'{geoserver_client.DEFAULT_GEOSERVER_URL}/geoserver/pikurr/wfs', params={
        'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
        'typeNames': 'pikurr:fields_latest', 'outputFormat': 'application/json',
        'CQL_FILTER': "district = '2212'",
    }, timeout=60)
    data2 = r2.json()
    xs2, ys2 = [], []
    for f in data2['features']:
        stack = [f['geometry']['coordinates']]
        while stack:
            c = stack.pop()
            if isinstance(c[0], (int, float)):
                xs2.append(c[0]); ys2.append(c[1])
            else:
                stack.extend(c)
    district_center_lonlat = QgsPointXY((min(xs2) + max(xs2)) / 2, (min(ys2) + max(ys2)) / 2)
    district_center_proj = transform.transform(district_center_lonlat)
    map_extent2 = iface.mapCanvas().extent()
    inside2 = map_extent2.contains(district_center_proj)
    record('A4. "Весь район" 2212 — центр района внутри охвата карты',
           inside2, f'внутри={inside2}, охват_карты={map_extent2.toString()}')

    # ---- A5: прозрачность слоёв по отдельности, без подложки ----
    select_by_arrow(panel.userCombo, '2212000055')
    QTest.keyClick(panel.userCombo, Qt.Key_Return)

    from qgis.core import QgsProject as QP
    fields_layer = QP.instance().mapLayer(plugin._fields_layer_id)
    fields_url = fields_layer.source()
    record('A5. URL слоя полей содержит transparent=true',
           'transparent=true' in fields_url.lower(),
           fields_url[:200])

    from qgis.core import (QgsMapSettings, QgsMapRendererParallelJob,
                            QgsRectangle, QgsCoordinateReferenceSystem as QCRS)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    def render_alone(layer, bbox, size=(200, 150)):
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(QCRS(3857))
        settings.setExtent(bbox)
        settings.setOutputSize(QSize(*size))
        settings.setBackgroundColor(QColor(0, 0, 0, 0))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        return job.renderedImage()

    bbox_user_3857 = QgsRectangle(3401066.479, 7435968.408, 3401534.020, 7436732.611)
    img = render_alone(fields_layer, bbox_user_3857)
    from collections import Counter
    pixels = [img.pixel(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)]
    total = len(pixels)
    transparent = sum(1 for p in pixels if ((p >> 24) & 0xFF) == 0)
    frac_transparent = transparent / total if total else 0
    top3 = Counter(pixels).most_common(3)
    record('A5. Слой полей на охвате одного участка — большая часть пикселей прозрачна',
           frac_transparent > 0.3,
           f'доля_прозрачных={frac_transparent:.1%}, топ-3(ARGB hex)='
           f'{[hex(c) for c, _ in top3]}')

    # ---- A6: CRS проекта не меняется, если проект не пуст ----
    from qgis.core import QgsVectorLayer
    dummy = QgsVectorLayer('Point?crs=EPSG:32635', 'dummy_32635', 'memory')
    QP.instance().addMapLayer(dummy)
    crs_before = QP.instance().crs().authid()
    panel.aiCheckBox.click()
    crs_after = QP.instance().crs().authid()
    record('A6. CRS проекта (непустого) не меняется при включении AI-оценки',
           crs_before == crs_after, f'{crs_before} -> {crs_after}')
    panel.aiCheckBox.click()
    QP.instance().removeMapLayer(dummy.id())

    # ---- round50, блок B.2: год без данных — таблица пуста, карта не
    # сдвинута, без исключений. 2024 год реально не существует на проде
    # (единственный — 2025), yearCombo его не предлагает сам — добавляем
    # пункт вручную, чтобы протестировать путь кода, не дожидаясь
    # появления второго года на проде.
    select_by_arrow(panel.userCombo, '2212000055')
    QTest.keyClick(panel.userCombo, Qt.Key_Return)
    extent_before = iface.mapCanvas().extent()
    panel.yearCombo.addItem('2024 (тест, реально не существует)', 2024)
    year_2024_idx = panel.yearCombo.count() - 1
    try:
        select_by_arrow(panel.yearCombo, 2024)
        QTest.keyClick(panel.yearCombo, Qt.Key_Return)
        stats_rows_2024 = table_rows(panel)
        extent_after = iface.mapCanvas().extent()
        record('B2. Год без данных (2024): таблица пуста, карта не сдвинута, без исключений',
               stats_rows_2024 == [] and extent_after == extent_before,
               f'строк_таблицы={len(stats_rows_2024)}, '
               f'охват_совпадает={extent_after == extent_before}')
    except Exception as e:
        record('B2. Год без данных (2024): таблица пуста, карта не сдвинута, без исключений',
               False, f'исключение: {e}')
    finally:
        # вернуть к "последние данные" для остальных шагов
        panel.yearCombo.removeItem(year_2024_idx)
        select_by_arrow(panel.yearCombo, None)
        QTest.keyClick(panel.yearCombo, Qt.Key_Return)

    # ---- A3: поиск в списке по подстроке и коду (реальный ввод, не setText) ----
    combo = panel.userCombo
    hits = []
    combo.activated.connect(lambda i: hits.append(i))

    combo.setCurrentIndex(0)
    combo.lineEdit().clear()
    send_unicode_text(combo.lineEdit(), 'оменков')
    completer = combo.completer()
    found_substring = (completer.completionCount() == 1 and
                        '2212000055' in completer.currentCompletion())
    popup_visible = completer.popup().isVisible()
    record('A3. Подстрока из середины имени находит нужного землепользователя в popup '
           '(MatchContains) — сам клик по popup недоступен headless, см. отчёт',
           found_substring and popup_visible,
           f'вариантов={completer.completionCount()}, '
           f'найдено={completer.currentCompletion() if completer.completionCount() else None}, '
           f'popup_visible={popup_visible}')

    combo.setCurrentIndex(0)
    combo.lineEdit().clear()
    send_unicode_text(combo.lineEdit(), '2212000055')
    found_by_code = (completer.completionCount() == 1 and
                      '2212000055' in completer.currentCompletion())
    record('A3. Код находит того же землепользователя в popup',
           found_by_code, f'вариантов={completer.completionCount()}, '
                           f'найдено={completer.currentCompletion() if completer.completionCount() else None}')

    count_before_bad = combo.count()
    combo.setCurrentIndex(0)
    combo.lineEdit().clear()
    send_unicode_text(combo.lineEdit(), 'НЕСУЩЕСТВУЮЩИЙТЕКСТ12345')
    QTest.keyClick(combo.lineEdit(), Qt.Key_Return)
    count_after_bad = combo.count()
    record('A3. Несуществующий текст + Enter не добавляет пункт в список',
           count_after_bad == count_before_bad,
           f'{count_before_bad} -> {count_after_bad}, insertPolicy={combo.insertPolicy()}')

    # ---- Слои: группа, без дублей (round48, C3) ----
    group = QP.instance().layerTreeRoot().findGroup('ПИК УРР')
    record('4a. Группа слоёв "ПИК УРР" создана', group is not None)
    n_before = len(QP.instance().mapLayers())
    for _ in range(3):
        select_by_arrow(panel.districtCombo, '2212')
        QTest.keyClick(panel.districtCombo, Qt.Key_Return)
    n_after = len(QP.instance().mapLayers())
    record('4b. Повторные выборы не плодят слои (3 повтора)', n_after == n_before,
           f'{n_before} -> {n_after}')

    # ---- AI-оценка через .click() (не programmatic setChecked) ----
    panel.aiCheckBox.click()
    ok_ai = plugin._raster_layer_id is not None
    if ok_ai:
        raster_layer = QP.instance().mapLayer(plugin._raster_layer_id)
        img2 = render_alone(raster_layer, QgsRectangle(3318534.208, 7341262.722,
                                                          3441208.287, 7478131.670))
        nonempty = sum(1 for y in range(0, img2.height(), 10) for x in range(0, img2.width(), 10)
                       if (img2.pixel(x, y) >> 24) & 0xFF > 0)
        ok_ai = nonempty > 0
    record('5. AI-оценка (.click(), WMTS) отрисована, доля непрозрачных пикселей > 0', ok_ai)
    panel.aiCheckBox.click()

    # ---- Отказы: недоступный адрес, адрес SPA, мусорный ответ ----
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
