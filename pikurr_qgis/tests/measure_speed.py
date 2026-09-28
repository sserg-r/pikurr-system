# -*- coding: utf-8 -*-
"""
round48, блок B1/B2: замер скорости операций плагина. Запускать ДО и
ПОСЛЕ правок блока B2 с одинаковым протоколом — единственный способ
понять, что правка B2 реально изменила.

Запуск (координаторская машина; qgis --code НЕ определяет __file__ —
см. CLAUDE.md, находка round47):

    env -u VIRTUAL_ENV -u PYTHONPATH -u http_proxy -u https_proxy \
        PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        QT_QPA_PLATFORM=offscreen \
        qgis --code pikurr_qgis/tests/measure_speed.py --nologo --noversioncheck

Плагин должен быть синхронизирован в тестовый профиль QGIS (та же
проблема повторного импорта из sys.modules, что в test_headless.py).
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

from pikurr_qgis import geoserver_client  # noqa: E402

N_REPS = 3
URL = geoserver_client.DEFAULT_GEOSERVER_URL


def timed(fn, n=N_REPS):
    times = []
    result = None
    for _ in range(n):
        t0 = time.time()
        result = fn()
        times.append(time.time() - t0)
    return times, result


def report(label, times):
    print(f'{label}: {[round(t, 3) for t in times]} с '
          f'(среднее {round(statistics.mean(times), 3)} с)', flush=True)


def measure_get_capabilities():
    import requests
    def wms_caps():
        r = requests.get(f'{URL}/geoserver/wms?service=WMS&version=1.1.1&request=GetCapabilities',
                          timeout=30)
        return len(r.content)
    times, size = timed(wms_caps)
    report('GetCapabilities /geoserver/wms (глобальный, все workspace)', times)
    print(f'  размер ответа: {size} байт', flush=True)


def measure_dialog_open():
    """Три запроса, которые делает load_server_data(): доступность,
    справочник районов, WPS gs:Query по levelsagg."""
    def open_seq():
        geoserver_client.check_service_availability(URL)
        try:
            geoserver_client.fetch_districts_reference(URL)
        except geoserver_client.GeoServerError:
            pass
        xml = _gs_query_xml()
        try:
            geoserver_client.wps_execute_json(URL, xml)
        except geoserver_client.GeoServerError:
            pass
    times, _ = timed(open_seq)
    report('Открытие диалога (доступность + справочник + gs:Query)', times)


def _gs_query_xml():
    return '''<?xml version="1.0" encoding="UTF-8"?><wps:Execute version="1.0.0" service="WPS" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.opengis.net/wps/1.0.0" xmlns:wfs="http://www.opengis.net/wfs" xmlns:wps="http://www.opengis.net/wps/1.0.0" xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc" xmlns:wcs="http://www.opengis.net/wcs/1.1.1" xmlns:xlink="http://www.w3.org/1999/xlink" xsi:schemaLocation="http://www.opengis.net/wps/1.0.0 http://schemas.opengis.net/wps/1.0.0/wpsAll.xsd">
                <ows:Identifier>gs:Query</ows:Identifier>
                <wps:DataInputs>
                    <wps:Input>
                    <ows:Identifier>features</ows:Identifier>
                    <wps:Reference mimeType="text/xml" xlink:href="http://geoserver/wfs" method="POST">
                        <wps:Body>
                        <wfs:GetFeature service="WFS" version="1.0.0" outputFormat="GML2" xmlns:pikurr="http://pikurr">
                            <wfs:Query typeName="pikurr:levelsagg"/>
                        </wfs:GetFeature>
                        </wps:Body>
                    </wps:Reference>
                    </wps:Input>
                    <wps:Input><ows:Identifier>attribute</ows:Identifier><wps:Data><wps:LiteralData>rn</wps:LiteralData></wps:Data></wps:Input>
                    <wps:Input><ows:Identifier>attribute</ows:Identifier><wps:Data><wps:LiteralData>usname</wps:LiteralData></wps:Data></wps:Input>
                    <wps:Input><ows:Identifier>attribute</ows:Identifier><wps:Data><wps:LiteralData>usern_co</wps:LiteralData></wps:Data></wps:Input>
                </wps:DataInputs>
                <wps:ResponseForm>
                    <wps:RawDataOutput mimeType="application/json"><ows:Identifier>result</ows:Identifier></wps:RawDataOutput>
                </wps:ResponseForm>
                </wps:Execute>'''


def measure_user_selection(user_prefix, label):
    """Полный цикл add_vec2() для одного землепользователя: слой полей
    (WMS, isValid), границы (2 WPS-запроса, как в 1.1.0), статистика."""
    from qgis.core import QgsRasterLayer

    def full_cycle():
        wms_fields_url = (f"IgnoreGetMapUrl=1&crs=CRS:84&dpiMode=7&format=image/png&layers=fields&styles"
                           f"&url={URL}/geoserver/pikurr/wms?CQL_FILTER=nr_user LIKE '{user_prefix}%'")
        layer = QgsRasterLayer(wms_fields_url, 'fields', 'wms')
        _ = layer.isValid()

        bounds_tpl_path = os.path.join(PLUGIN_DIR, 'wps_templates', 'bounds.xml')
        with open(bounds_tpl_path, encoding='utf-8') as fh:
            bounds_tpl = fh.read()
        filt = (f'<ogc:Filter><ogc:PropertyIsLike wildCard="*" singleChar="." escape="!">'
                f'<ogc:PropertyName>nr_user</ogc:PropertyName><ogc:Literal>{user_prefix}*</ogc:Literal>'
                f'</ogc:PropertyIsLike></ogc:Filter>')
        bounds_xml = bounds_tpl.format(filter=filt)
        # 1.1.0: первый запрос через wps_execute_json (JSON) намеренно
        # проваливается (bounds.xml не просит JSON) — код падает в
        # except и уходит во ВТОРОЙ запрос сырым requests.post. Тайминг
        # должен честно отразить обе попытки (см. A5 отчёта).
        try:
            geoserver_client.wps_execute_json(URL, bounds_xml)
        except geoserver_client.GeoServerError:
            import requests
            requests.post(f'{URL}/geoserver/wps', data=bounds_xml,
                           headers={"Content-Type": "text/xml"}, timeout=15)

        agg_tpl_path = os.path.join(PLUGIN_DIR, 'wps_templates', 'aggregate.xml')
        with open(agg_tpl_path, encoding='utf-8') as fh:
            agg_tpl = fh.read()
        agg_xml = agg_tpl.format(filter=filt)
        try:
            geoserver_client.wps_execute_json(URL, agg_xml)
        except geoserver_client.GeoServerError:
            pass

    times, _ = timed(full_cycle)
    report(label, times)


def measure_raster_render(bbox_3857, label):
    """headless-отрисовка растра AI-оценки на охвате (QgsMapRendererParallelJob),
    доля непрозрачных пикселей — правило непустых ответов."""
    from qgis.core import (QgsRasterLayer, QgsProject, QgsMapSettings,
                            QgsMapRendererParallelJob, QgsRectangle,
                            QgsCoordinateReferenceSystem)
    from qgis.PyQt.QtCore import QSize

    wms_url = f"crs=CRS:84&dpiMode=7&format=image/png&layers=pikurr:image_assessment&styles&url={URL}/geoserver/wms?version=1.1.0"
    layer = QgsRasterLayer(wms_url, 'base_map', 'wms')
    if not layer.isValid():
        print(f'{label}: СЛОЙ НЕВАЛИДЕН, пропуск', flush=True)
        return

    def render_once():
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(QgsCoordinateReferenceSystem(3857))
        settings.setExtent(QgsRectangle(*bbox_3857))
        settings.setOutputSize(QSize(1600, 900))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        return img

    times, img = timed(render_once)
    report(f'Отрисовка AI-оценки 1600x900, {label}', times)
    _report_nonempty_fraction(img, label)


def measure_vector_render(bbox_3857, label):
    from qgis.core import (QgsVectorLayer, QgsMapSettings, QgsMapRendererParallelJob,
                            QgsRectangle, QgsCoordinateReferenceSystem)
    from qgis.PyQt.QtCore import QSize

    wms_url = (f"IgnoreGetMapUrl=1&crs=CRS:84&dpiMode=7&format=image/png&layers=fields&styles"
               f"&url={URL}/geoserver/pikurr/wms")
    from qgis.core import QgsRasterLayer
    layer = QgsRasterLayer(wms_url, 'fields', 'wms')
    if not layer.isValid():
        print(f'{label}: СЛОЙ ПОЛЕЙ НЕВАЛИДЕН, пропуск', flush=True)
        return

    def render_once():
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(QgsCoordinateReferenceSystem(3857))
        settings.setExtent(QgsRectangle(*bbox_3857))
        settings.setOutputSize(QSize(1600, 900))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        return job.renderedImage()

    times, img = timed(render_once)
    report(f'Отрисовка слоя полей 1600x900, {label}', times)
    _report_nonempty_fraction(img, label)


def _report_nonempty_fraction(img, label):
    if img is None or img.isNull():
        print(f'  {label}: изображение пустое/null', flush=True)
        return
    w, h = img.width(), img.height()
    sample_step = max(1, (w * h) // 20000)  # выборка, не все пиксели — быстрее
    nonempty = 0
    total = 0
    idx = 0
    for y in range(0, h, max(1, h // 140)):
        for x in range(0, w, max(1, w // 140)):
            px = img.pixel(x, y)
            alpha = (px >> 24) & 0xFF
            if alpha > 0:
                nonempty += 1
            total += 1
    frac = nonempty / total if total else 0
    print(f'  доля непрозрачных пикселей: {frac:.1%} ({nonempty}/{total} проб)', flush=True)


def main():
    print('=== round48 блок B1: замер "до" (код 1.1.0) ===', flush=True)
    print(f'Машина: координаторская, точка входа: {URL}, повторов: {N_REPS}\n', flush=True)

    measure_get_capabilities()
    print(flush=True)

    measure_dialog_open()
    print(flush=True)

    measure_user_selection('2212000055', 'Выбор землепользователя 2212000055 (полный цикл)')
    print(flush=True)

    measure_user_selection('22120', 'Весь район 2212 (usids[0][:5]="22120", полный цикл)')
    print(flush=True)

    # bbox_3857 — получены фактом перед замером: прямой WFS-запрос
    # GetFeature по nr_user LIKE '2212%'/'2212000055%' на pikurr:fields_latest,
    # свёртка min/max координат по всем features, перевод lon/lat->3857
    # через REPIKURR/tools/tile_math.py (не выдумано, не с потолка).
    bbox_district_2212 = [3318534.208, 7341262.722, 3441208.287, 7478131.670]  # 9039 объектов
    bbox_user = [3401066.479, 7435968.408, 3401534.020, 7436732.611]  # 2212000055, 1 объект

    measure_raster_render(bbox_district_2212, 'охват района 2212')
    measure_raster_render(bbox_user, 'охват землепользователя 2212000055')
    measure_vector_render(bbox_district_2212, 'охват района 2212')
    measure_vector_render(bbox_user, 'охват землепользователя 2212000055')

    print('\n=== конец замера ===', flush=True)


main()
import os as _os
_os.abort() if False else _os._exit(0)
