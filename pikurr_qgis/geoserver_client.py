# -*- coding: utf-8 -*-
"""
Клиент к GeoServer для плагина pikurr (round47, блок A/C; round48,
блоки A3/A4 — переход на сетевой стек QGIS, проверка доступности по
содержимому).

Вынесено из pikurr.py, чтобы код можно было проверить headless-тестом
без поднятия панели QGIS. Не содержит ничего, что должно жить в
pikurr.py — только сеть и разбор ответов.

История: до round47 адрес сервера угадывался перебором
(localhost:8080 -> http://geobotany.xyz, второй домен никогда не
существовал — docs/round45-qgis-recon.md) и падение оборачивалось
`raise Exception(...)` до показа диалога пользователю. round47 сделал
адрес явной настройкой (QSettings) с прод-значением по умолчанию.

round48, блок A4: весь сетевой код переведён с `requests` на
`QgsBlockingNetworkRequest` (сетевой стек QGIS,
`QgsNetworkAccessManager`) — `requests` не видит настроек прокси/SSL из
QGIS ("Параметры -> Сеть"), из-за чего в сети с прокси у пользователя
работали бы только слои (через провайдер QGIS), но не списки и
статистика (через `requests`). `QgsBlockingNetworkRequest` синхронный —
не решает проблему блокировки интерфейса саму по себе (см. отчёт,
блок B2.4), но обязателен для корректности в сетях с прокси.

round48, блок A3: `check_service_availability()` раньше запрашивал
`{url}/geoserver` без слэша — этот путь не попадает под правило
`handle /geoserver/*` в Caddyfile и уходит во фронтенд, который отдаёт
`index.html` с кодом 200 на любой путь. Проверка была технически
"всегда зелёной" — и на боевом сервере, и на любом чужом SPA-сайте.
Теперь проверка — по содержимому: WPS `GetCapabilities`, разбор XML,
поиск корневого элемента `Capabilities` и трёх нужных процессов.
"""
import json

DEFAULT_GEOSERVER_URL = "https://geobotany.of.by"
SETTINGS_KEY = "pikurr/geoserver_url"
REQUEST_TIMEOUT_S = 10

REQUIRED_WPS_PROCESSES = ("gs:Query", "vec:Aggregate", "vec:Bounds")


class GeoServerError(Exception):
    """Сетевая ошибка или отказ сервиса — предназначена для показа
    пользователю текстом, не для необработанного падения диалога."""


def get_geoserver_url():
    """Текущий адрес сервера: пользовательская настройка (QSettings),
    если задана, иначе прод по умолчанию."""
    from qgis.PyQt.QtCore import QSettings
    value = QSettings().value(SETTINGS_KEY, "")
    value = (value or "").strip()
    return value.rstrip("/") if value else DEFAULT_GEOSERVER_URL


def set_geoserver_url(url):
    """Сохраняет адрес сервера между запусками QGIS. Пустая строка —
    сброс к прод-значению по умолчанию."""
    from qgis.PyQt.QtCore import QSettings
    QSettings().setValue(SETTINGS_KEY, (url or "").strip().rstrip("/"))


def _blocking_get(url, timeout_s=REQUEST_TIMEOUT_S):
    """round48, A4: GET через сетевой стек QGIS. Возвращает
    (status_code_or_none, body_text, error_message_or_empty)."""
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
    from qgis.PyQt.QtNetwork import QNetworkRequest

    req = QNetworkRequest(QUrl(url))
    bnr = QgsBlockingNetworkRequest()
    err = bnr.get(req, forceRefresh=True)
    if err != QgsBlockingNetworkRequest.NoError:
        return None, "", bnr.errorMessage() or f"код ошибки сети {err}"
    reply = bnr.reply()
    status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    body = bytes(reply.content()).decode("utf-8", errors="replace")
    return status, body, ""


def _blocking_post(url, data, content_type="text/xml", timeout_s=REQUEST_TIMEOUT_S):
    """round48, A4: POST через сетевой стек QGIS."""
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    req = QNetworkRequest(QUrl(url))
    req.setHeader(QNetworkRequest.ContentTypeHeader, content_type)
    bnr = QgsBlockingNetworkRequest()
    payload = data.encode("utf-8") if isinstance(data, str) else data
    err = bnr.post(req, payload)
    if err != QgsBlockingNetworkRequest.NoError:
        return None, "", bnr.errorMessage() or f"код ошибки сети {err}"
    reply = bnr.reply()
    status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    body = bytes(reply.content()).decode("utf-8", errors="replace")
    return status, body, ""


def check_service_availability(url, timeout=REQUEST_TIMEOUT_S):
    """round48, A3: проверка ПО СОДЕРЖИМОМУ, не по коду ответа —
    `{url}/geoserver` (без слэша) отдаёт 200 и на боевом GeoServer, и на
    любом чужом SPA-сайте (try_files/index.html), поэтому раньше эта
    проверка не могла отличить "сервер лежит" от "это вообще не
    GeoServer". Используем WPS GetCapabilities (POST, тот же путь, что
    и все рабочие запросы плагина) и разбираем XML.

    :returns: (ok: bool, detail: str) — detail всегда заполнен, даже
        при ok=True.
    """
    from xml.etree import ElementTree as ET

    wps_url = f"{url}/geoserver/wps"
    caps_xml = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<wps:GetCapabilities xmlns:wps="http://www.opengis.net/wps/1.0.0" '
                'service="WPS"/>')
    status, body, err = _blocking_post(wps_url, caps_xml)
    if err:
        return False, f"{wps_url} недоступен: {err}"
    if status != 200:
        return False, f"{wps_url} вернул HTTP {status} — недоступен"

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return False, f"{wps_url}: ответ не XML (по этому адресу не GeoServer) — {body[:120]}"

    root_local = root.tag.split('}')[-1]
    if root_local != "Capabilities":
        return False, (f"{wps_url}: ответ не похож на WPS Capabilities "
                        f"(корневой элемент <{root_local}>) — по этому адресу не GeoServer")

    body_text = body
    missing = [p for p in REQUIRED_WPS_PROCESSES if p not in body_text]
    if missing:
        return False, (f"{wps_url}: GeoServer отвечает, но не хватает процессов "
                        f"{missing} — обновление образа могло убрать WPS-расширение")

    return True, f"{wps_url} -> WPS Capabilities, все процессы на месте"


def wps_execute_json(geoserver_url, xml_body, timeout=REQUEST_TIMEOUT_S):
    """POST WPS Execute, ожидает JSON в ответе. Поднимает GeoServerError
    с понятным текстом на любой отказ (сеть, таймаут, ServiceException,
    пустое/не-JSON тело) — не даёт вызывающему коду упасть на
    json.loads() необработанным исключением."""
    url = f"{geoserver_url}/geoserver/wps"
    status, body, err = _blocking_post(url, xml_body)
    if err:
        raise GeoServerError(f"нет ответа от {url}: {err}")
    if status != 200:
        raise GeoServerError(f"{url} вернул HTTP {status}")
    if not body.strip():
        raise GeoServerError(f"{url} вернул пустой ответ")
    if _is_service_exception(body):
        raise GeoServerError(f"{url} вернул ошибку сервиса: {body[:300]}")
    try:
        return json.loads(body)
    except (ValueError, json.JSONDecodeError):
        raise GeoServerError(f"{url} вернул не-JSON ответ: {body[:300]}")


def wps_execute_raw(geoserver_url, xml_body, timeout=REQUEST_TIMEOUT_S):
    """round48, A5: POST WPS Execute, возвращает СЫРОЙ текст ответа
    (не пытается разобрать как JSON) — для процессов вроде `vec:Bounds`,
    у которых `RawDataOutput` без `mimeType` (сервер отвечает
    GML/текстом, не JSON). Один запрос, один разбор — раньше на этот
    же ответ сначала пробовали JSON (гарантированный отказ) и только
    потом парсили как XML вторым отдельным запросом."""
    url = f"{geoserver_url}/geoserver/wps"
    status, body, err = _blocking_post(url, xml_body)
    if err:
        raise GeoServerError(f"нет ответа от {url}: {err}")
    if status != 200:
        raise GeoServerError(f"{url} вернул HTTP {status}")
    if not body.strip():
        raise GeoServerError(f"{url} вернул пустой ответ")
    if _is_service_exception(body):
        raise GeoServerError(f"{url} вернул ошибку сервиса: {body[:300]}")
    return body


def _is_service_exception(text):
    """round47, A3.2: ServiceExceptionReport/ExceptionReport при HTTP 200
    — класс отказа №8/№13 из HANDOFF_pikurr_v2.md, не путать с пустыми
    (но валидными) данными. WFS/WMS/WPS все могут вернуть это тело."""
    head = text[:400].lstrip()
    return (
        "ServiceExceptionReport" in head
        or "ExceptionReport" in head
        or head.startswith("<ows:ExceptionReport")
    )


def fetch_districts_reference(geoserver_url, timeout=REQUEST_TIMEOUT_S):
    """round47, A2: справочник «код района -> название» с сервера, тот
    же файл, что генерируется из REPIKURR/repikurr/src/constants.js
    (tools/gen_districts_ref.py) — единственный экземпляр данных вне
    исходников фронтенда, а не третья независимая копия в плагине.

    :returns: (oblasts: dict, districts: dict) — оба код->название.
    :raises GeoServerError: сеть/отказ/некорректный файл.
    """
    url = f"{geoserver_url}/districts_ref.json"
    status, body, err = _blocking_get(url)
    if err:
        raise GeoServerError(f"нет ответа от {url}: {err}")
    if status != 200:
        raise GeoServerError(f"{url} вернул HTTP {status}")
    try:
        data = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        raise GeoServerError(f"{url} вернул не-JSON ответ: {body[:200]}")
    oblasts = data.get("oblasts") or {}
    districts = data.get("districts") or {}
    if not districts:
        raise GeoServerError(f"{url}: справочник районов пуст")
    return oblasts, districts


def fetch_year_district_data(geoserver_url, timeout=REQUEST_TIMEOUT_S):
    """round48, C2.1: список лет — из того же источника, что витрина
    (`REPIKURR/repikurr/src/services/geoserver.js::loadYearDistrictData()`),
    не отдельная догадка. `/static/year_district.json` собирается
    `deliver.py` при каждой доставке (round23).

    :returns: (years: list[int], districts_by_year: dict[str, set[str]])
    """
    url = f"{geoserver_url}/static/year_district.json"
    status, body, err = _blocking_get(url)
    if err:
        raise GeoServerError(f"нет ответа от {url}: {err}")
    if status != 200:
        raise GeoServerError(f"{url} вернул HTTP {status}")
    try:
        data = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        raise GeoServerError(f"{url} вернул не-JSON ответ: {body[:200]}")
    years = sorted(data.get("years") or [])
    districts_by_year = {
        y: set(ds) for y, ds in (data.get("districtsByYear") or {}).items()
    }
    return years, districts_by_year
