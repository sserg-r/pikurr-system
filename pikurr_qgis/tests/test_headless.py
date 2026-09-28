# -*- coding: utf-8 -*-
"""
round47, блок B3/D: headless-проверка плагина по образцу smoke.mjs, но
для PyQGIS. Не заменяет проверку в реальном GUI (блок D этого раунда) —
QApplication здесь offscreen, диалог реально не рисуется на экране, но
весь код плагина (сеть, разбор ответов, построение списков, добавление
слоёв, запрос статистики) исполняется по-настоящему, против реального
прод-сервера, без моков.

Эталон для сверки (round46, блок A.4, подтверждено двумя независимыми
путями): землепользователь 2212000055 ("Фоменков Г.В.", код в
comboUsers начинается с "22120"), район 2212 (Витебский) — 1 объект,
5.6 га, сценарий tillage.

Запуск (координаторская машина, .venv ломает встроенный Python QGIS —
см. CLAUDE.md, "Ловушки" round45/46):

    env -u VIRTUAL_ENV -u PYTHONPATH -u http_proxy -u https_proxy \
        PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        QT_QPA_PLATFORM=offscreen \
        qgis --code pikurr_qgis/tests/test_headless.py --nologo --noversioncheck

Код возврата: печатает PASS/FAIL по каждому шагу, в конце —
"HEADLESS: N/M PASS" (0 — все шаги прошли, 1 — есть FAIL). Не проверяет
реальный QGIS GUI (пункты, требующие человека — блок D отчёта раунда 47).

Требование к среде: плагин должен быть импортируем как `pikurr_qgis`
(проще всего — установлен в тестовый профиль QGIS, `~/.local/share/
QGIS/QGIS3/profiles/default/python/plugins/pikurr_qgis/`, синхронизирован
с этим каталогом перед прогоном) — если нет, скрипт ищет `pikurr_qgis/`
рядом с текущим рабочим каталогом.

Находка round47 (стоила часа отладки — оставлено на будущее): `qgis
--code <script>` НЕ определяет `__file__` в globals исполняемого
скрипта. Код, обращающийся к `__file__` (типичный способ найти "каталог
рядом с этим файлом"), ловит `NameError`, который в этом режиме не
печатается в консоль как traceback, а рвётся в обработчик исключений
QGIS, показывающий модальный диалог — под offscreen-платформой диалог
невидим, но блокирует процесс НАВСЕГДА без единой строки вывода
(выглядит как зависание, не как ошибка). Не использовать `__file__` в
скриптах для `qgis --code`.
"""
import os
import sys


def _find_plugin_dir():
    # round47: `qgis --code <script>` НЕ определяет `__file__` в globals
    # исполняемого скрипта (проверено фактом) — код, полагавшийся на
    # `os.path.dirname(os.path.abspath(__file__))`, ловит NameError,
    # который QGIS не печатает в консоль, а показывает как модальный
    # диалог; под offscreen-платформой (headless-тесты) диалог невидим,
    # но блокирует процесс НАВСЕГДА — выглядит как зависание без единой
    # строки в выводе. Путь к плагину берём из уже загруженного модуля
    # (плагин почти всегда уже активен в тестовом профиле QGIS), с
    # фолбэком на текущий каталог для случая "плагин не установлен".
    try:
        import pikurr_qgis
        return pikurr_qgis.__path__[0]
    except ImportError:
        pass
    for candidate in (os.path.join(os.getcwd(), 'pikurr_qgis'),
                       os.path.join(os.getcwd(), '..', 'pikurr_qgis')):
        if os.path.isdir(candidate):
            sys.path.insert(0, os.path.dirname(os.path.abspath(candidate)))
            return os.path.abspath(candidate)
    raise RuntimeError(
        'не удалось найти каталог pikurr_qgis — запустите скрипт с рабочим '
        'каталогом внутри репозитория или установите плагин в профиль QGIS')


PLUGIN_DIR = _find_plugin_dir()
from pikurr_qgis import geoserver_client  # noqa: E402

RESULTS = []


def record(name, ok, detail=''):
    RESULTS.append((name, ok))
    status = 'PASS' if ok else 'FAIL'
    # flush=True обязателен: скрипт завершается через os._exit() (см.
    # низ файла), который не сбрасывает буферизованный stdout — без
    # этого весь вывод при перенаправлении в файл/pipe терялся молча
    # (round47, найдено фактом при первом прогоне этого теста).
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''), flush=True)


def main():
    url = geoserver_client.DEFAULT_GEOSERVER_URL

    ok, detail = geoserver_client.check_service_availability(url)
    record('1. Сервер доступен (HTTPS, прод по умолчанию)', ok, detail)
    if not ok:
        print('HEADLESS: сервер недоступен, дальнейшие шаги пропущены', flush=True)
        _summary()
        return

    try:
        oblasts, districts = geoserver_client.fetch_districts_reference(url)
        record('2. Справочник районов с сервера', bool(districts),
               f'{len(districts)} районов, {len(oblasts)} областей')
    except geoserver_client.GeoServerError as e:
        record('2. Справочник районов с сервера', False, str(e))
        oblasts, districts = {}, {}

    xml = '''<?xml version="1.0" encoding="UTF-8"?><wps:Execute version="1.0.0" service="WPS" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.opengis.net/wps/1.0.0" xmlns:wfs="http://www.opengis.net/wfs" xmlns:wps="http://www.opengis.net/wps/1.0.0" xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc" xmlns:wcs="http://www.opengis.net/wcs/1.1.1" xmlns:xlink="http://www.w3.org/1999/xlink" xsi:schemaLocation="http://www.opengis.net/wps/1.0.0 http://schemas.opengis.net/wps/1.0.0/wpsAll.xsd">
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
    try:
        j = geoserver_client.wps_execute_json(url, xml)
        record('3. WPS gs:Query (levelsagg -> список районов)', True,
               f'{len(j.get("features", []))} записей')
    except geoserver_client.GeoServerError as e:
        record('3. WPS gs:Query (levelsagg -> список районов)', False, str(e))
        _summary()
        return

    target_district = '2212'
    target_user_prefix = '2212000055'
    codes = [f['properties']['usern_co'] for f in j['features']
             if f['properties']['rn'] == target_district
             and f['properties']['usern_co'].startswith(target_user_prefix)]
    record('4. Эталонный землепользователь найден в списке района 2212',
           len(codes) >= 1, f'{len(codes)} совпадений по префиксу {target_user_prefix}')

    aggregate_template = os.path.join(PLUGIN_DIR, 'wps_templates', 'aggregate.xml')
    with open(aggregate_template, encoding='utf-8') as fh:
        agg_tpl = fh.read()
    filt = f'''<ogc:Filter>
        <ogc:PropertyIsLike wildCard="*" singleChar="." escape="!">
            <ogc:PropertyName>nr_user</ogc:PropertyName>
            <ogc:Literal>{target_user_prefix}*</ogc:Literal>
        </ogc:PropertyIsLike>
    </ogc:Filter>'''
    agg_xml = agg_tpl.format(filter=filt)
    try:
        jsstat = geoserver_client.wps_execute_json(url, agg_xml)
        rows = jsstat.get('AggregationResults', [])
        tillage = next((r for r in rows if r[0] == 'tillage'), None)
        ok = tillage is not None and tillage[1] == 1 and abs(tillage[2] - 5.6) < 0.05
        record('5. Статистика по эталону совпадает с round46 (1 объект, 5.6 га, tillage)',
               ok, f'получено: {tillage}')
    except geoserver_client.GeoServerError as e:
        record('5. Статистика по эталону совпадает с round46 (1 объект, 5.6 га, tillage)',
               False, str(e))

    # Независимая сверка (не тем же кодом плагина) — прямой WFS-запрос.
    import requests
    try:
        wfs_url = (f'{url}/geoserver/pikurr/wfs?service=WFS&version=2.0.0&request=GetFeature'
                   f"&typeName=pikurr:fields_latest&outputFormat=application/json"
                   f"&CQL_FILTER=nr_user%20LIKE%20'{target_user_prefix}%25'")
        r = requests.get(wfs_url, timeout=15)
        data = r.json()
        n_features = len(data.get('features', []))
        area_sum = sum(f['properties'].get('area_ha', 0) for f in data.get('features', []))
        ok = n_features == 1 and abs(area_sum - 5.6) < 0.05
        record('6. Независимая сверка прямым WFS (не через код плагина)', ok,
               f'{n_features} объектов, {area_sum:.2f} га')
    except Exception as e:
        record('6. Независимая сверка прямым WFS (не через код плагина)', False, str(e))

    _summary()


def _summary():
    n_pass = sum(1 for _, ok in RESULTS if ok)
    print(f'HEADLESS: {n_pass}/{len(RESULTS)} PASS', flush=True)


main()
# `qgis --code <script>` запускает скрипт внутри уже поднятого
# приложения и не завершает процесс сам по себе (событийный цикл
# продолжает работать бесконечно под offscreen-платформой) — форсируем
# выход, иначе процесс висит и его приходится убивать вручную.
import os
os._exit(0 if all(ok for _, ok in RESULTS) else 1)
