# -*- coding: utf-8 -*-
"""
Клиент к GeoServer для плагина pikurr (round47, блок A/C).

Вынесено из pikurr.py, чтобы код можно было проверить headless-тестом
(tests/test_headless.py) без поднятия диалога QGIS. Не содержит ничего,
что должно жить в pikurr.py — только сеть и разбор ответов.

История: до round47 адрес сервера угадывался перебором
(localhost:8080 -> http://geobotany.xyz, второй домен никогда не
существовал — docs/round45-qgis-recon.md) и падение оборачивалось
`raise Exception(...)` до показа диалога пользователю. Теперь адрес —
явная настройка (QSettings) с прод-значением по умолчанию, а сетевые
ошибки не прерывают работу диалога.
"""
import json

DEFAULT_GEOSERVER_URL = "https://geobotany.of.by"
SETTINGS_KEY = "pikurr/geoserver_url"
REQUEST_TIMEOUT_S = 10


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


def check_service_availability(url, timeout=REQUEST_TIMEOUT_S):
    """Проверяет доступность GeoServer по URL.

    :returns: (ok: bool, detail: str) — detail всегда заполнен, даже
        при ok=True (что именно проверено), чтобы можно было показать
        пользователю причину отказа без повторной попытки.
    """
    import requests
    from requests.exceptions import RequestException
    probe = f"{url}/geoserver"
    try:
        # round47, A1.4: allow_redirects=True (по умолчанию requests) —
        # достаточно для HTTP->HTTPS редиректа от Caddy, проверено фактом
        # (docs/round47-qgis-plugin.md, блок A1).
        response = requests.get(probe, timeout=timeout)
        if response.status_code == 200:
            return True, f"{probe} -> 200"
        return False, f"{probe} -> HTTP {response.status_code}"
    except RequestException as e:
        return False, f"{probe} -> {e.__class__.__name__}: {e}"


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


def wps_execute_json(geoserver_url, xml_body, timeout=REQUEST_TIMEOUT_S):
    """POST WPS Execute, ожидает JSON в ответе. Поднимает GeoServerError
    с понятным текстом на любой отказ (сеть, таймаут, ServiceException,
    пустое/не-JSON тело) — не даёт вызывающему коду упасть на
    json.loads() необработанным исключением."""
    import requests
    from requests.exceptions import RequestException
    url = f"{geoserver_url}/geoserver/wps"
    try:
        r = requests.post(url, data=xml_body.encode("utf-8"), timeout=timeout)
    except RequestException as e:
        raise GeoServerError(f"нет ответа от {url}: {e.__class__.__name__}: {e}")

    if r.status_code != 200:
        raise GeoServerError(f"{url} вернул HTTP {r.status_code}")

    text = r.text
    if not text.strip():
        raise GeoServerError(f"{url} вернул пустой ответ")
    if _is_service_exception(text):
        raise GeoServerError(f"{url} вернул ошибку сервиса: {text[:300]}")

    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        raise GeoServerError(f"{url} вернул не-JSON ответ: {text[:300]}")


def fetch_districts_reference(geoserver_url, timeout=REQUEST_TIMEOUT_S):
    """round47, A2: справочник «код района -> название» с сервера, тот
    же файл, что генерируется из REPIKURR/repikurr/src/constants.js
    (tools/gen_districts_ref.py) — единственный экземпляр данных вне
    исходников фронтенда, а не третья независимая копия в плагине.

    :returns: (oblasts: dict, districts: dict) — оба код->название.
    :raises GeoServerError: сеть/отказ/некорректный файл.
    """
    import requests
    from requests.exceptions import RequestException
    # Справочник — статический файл фронтенда, лежит рядом с index.html,
    # не под /geoserver — тот же хост, что geoserver_url (Caddy отдаёт
    # оба с одного домена).
    url = f"{geoserver_url}/districts_ref.json"
    try:
        r = requests.get(url, timeout=timeout)
    except RequestException as e:
        raise GeoServerError(f"нет ответа от {url}: {e.__class__.__name__}: {e}")
    if r.status_code != 200:
        raise GeoServerError(f"{url} вернул HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise GeoServerError(f"{url} вернул не-JSON ответ: {r.text[:200]}")
    oblasts = data.get("oblasts") or {}
    districts = data.get("districts") or {}
    if not districts:
        raise GeoServerError(f"{url}: справочник районов пуст")
    return oblasts, districts
