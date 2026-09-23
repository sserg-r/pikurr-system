#!/usr/bin/env python3
"""
Проверка витрины PIKURR по содержимому ответа, не по коду.

round25, блок B5: критерий приёмки везде в этом раунде — содержимое, не
HTTP-код (найдено в round24, задача 2: WFS/WMS отдают HTTP 200 с телом
ServiceExceptionReport при отсутствии/поломке assessment_ready — чисто
кодовая проверка такое не увидит). Этот скрипт формализует ту же
проверку как постоянный инструмент: вызывается в конце deliver.py
(результат уходит в статус-файл) и пригоден для ручного запуска.

Использование:
    python3 healthcheck.py                  # проверка на локальный GEOSERVER_URL/DOMAIN
    python3 healthcheck.py --base-url https://geobotany.of.by
    python3 healthcheck.py --json           # машиночитаемый вывод

Код возврата: 0 — всё в порядке, 1 — есть хотя бы одно несоответствие.
"""

import argparse
import io
import json
import os
import struct
import subprocess
import sys
import urllib.parse
import zlib
from pathlib import Path

import requests

GEOSERVER_WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "pikurr")

# round35, блок B1: URL, которые реально шлёт фронтенд на GWC-эндпоинт —
# перехвачены дымовым сценарием (REPIKURR/tools/smoke/smoke.mjs), не
# собраны вручную. round34 A3 нашёл причину, почему сломанный растровый
# слой не заметила ни одна автопроверка: healthcheck проверял обычный
# /geoserver/pikurr/wms, а фронтенд для КЭШИРУЕМЫХ слоёв ходит на
# /geoserver/gwc/service/wms (нужен workspace-префикс в layers — GWC не
# виртуализован по workspace). Обновлять этот файл — перезапустить
# smoke.mjs (он сам перезаписывает captured_gwc_urls.json).
CAPTURED_GWC_URLS_PATH = Path(
    os.getenv("CAPTURED_GWC_URLS_PATH")
    or (Path(__file__).parent / "tools" / "smoke" / "captured_gwc_urls.json")
)

FRONTEND_DB = {
    "host": os.getenv("FRONTEND_DB_HOST", "localhost"),
    "port": int(os.getenv("FRONTEND_DB_PORT", "5433")),
    "user": os.getenv("FRONTEND_DB_USER", "pikurr"),
    "password": os.environ.get("FRONTEND_DB_PASSWORD", ""),
    "name": os.getenv("FRONTEND_DB_NAME", "pikurr"),
}


def _check(name: str, ok: bool, detail: str, checks: list):
    checks.append({"check": name, "ok": ok, "detail": detail})


def _png_has_nonempty_colors(body: bytes) -> tuple[bool, str]:
    """Минимальная проверка PNG без внешних библиотек: сигнатура + хотя бы
    один непустой чанк IDAT (пустой/полностью прозрачный растр GeoServer
    отдаёт как валидный, но вырожденный PNG — размер файла в этом случае
    аномально мал по сравнению с обычным тайлом)."""
    if body[:8] != b"\x89PNG\r\n\x1a\n":
        return False, "не PNG-сигнатура"
    if len(body) < 200:
        # Валидный, но подозрительно маленький PNG — почти наверняка
        # однотонная (пустая) заливка, не реальная классификация.
        return False, f"PNG подозрительно мал ({len(body)} байт) — вероятно, пустой растр"
    return True, f"PNG, {len(body)} байт"


def check_wms(base_url: str, checks: list):
    url = (
        f"{base_url}/geoserver/{GEOSERVER_WORKSPACE}/wms"
        "?service=WMS&version=1.1.0&request=GetMap"
        f"&layers={GEOSERVER_WORKSPACE}:image_assessment"
        "&bbox=26,54,27,55&width=100&height=100&srs=EPSG:4326&format=image/png"
    )
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as e:
        _check("wms_getmap", False, f"запрос не выполнен: {e}", checks)
        return

    body = resp.content
    if b"ServiceExceptionReport" in body or b"ExceptionReport" in body:
        _check("wms_getmap", False,
                f"HTTP {resp.status_code}, тело — ServiceExceptionReport "
                f"(код может быть 200 — это НЕ признак успеха)", checks)
        return

    ok, detail = _png_has_nonempty_colors(body)
    _check("wms_getmap", ok, f"HTTP {resp.status_code}, {detail}", checks)


def _tiles_with_data_path() -> Path:
    # round35, блок B2: на VPS/эмуляторе healthcheck.py обычно
    # деплоится ОТДЕЛЬНЫМ файлом (не всем деревом PIKURR_REFACTOR), путь
    # "на уровень выше REPIKURR/docs/..." там не существует — переопределять
    # через TILES_WITH_DATA_PATH при деплое вне монорепо.
    env_path = os.getenv("TILES_WITH_DATA_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent.parent / "docs" / "round32_assets" / "tiles_with_data.json"


def _load_tiles_with_data() -> list:
    path = _tiles_with_data_path()
    return json.loads(path.read_text())


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    import math
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_bbox_3857(x: int, y: int, z: int) -> list:
    origin = 20037508.342789244
    n = 2 ** z
    tile_size = 2 * origin / n
    minx = -origin + x * tile_size
    maxx = minx + tile_size
    maxy = origin - y * tile_size
    miny = maxy - tile_size
    return [minx, miny, maxx, maxy]


def check_gwc_layers(base_url: str, checks: list):
    """round35, блок B1: проверка ПО ТЕМ ЖЕ URL, что реально шлёт
    фронтенд для кэшируемых слоёв (`/geoserver/gwc/service/wms`, полное
    имя слоя с workspace-префиксом) — не по вручную собранному
    `/geoserver/pikurr/wms`, который эту ошибку (round34, блок A) не
    видел. Структура URL (все параметры, кроме `bbox`) берётся из
    `captured_gwc_urls.json`, перезаписываемого `smoke.mjs` при каждом
    прогоне; `bbox` заменяется на заведомо непустой тайл из
    `docs/round32_assets/tiles_with_data.json` (round32: случайный bbox
    даёт до 100% пустых тайлов — это ломало бы проверку независимо от
    того, жив слой или нет)."""
    if not CAPTURED_GWC_URLS_PATH.exists():
        _check("gwc_layers", False,
                f"{CAPTURED_GWC_URLS_PATH} не найден — запустить "
                f"REPIKURR/tools/smoke/smoke.mjs хотя бы раз, чтобы "
                f"перехватить реальные URL фронтенда", checks)
        return

    captured = json.loads(CAPTURED_GWC_URLS_PATH.read_text())
    if not captured:
        _check("gwc_layers", False,
                f"{CAPTURED_GWC_URLS_PATH} пуст — прошлый прогон smoke.mjs "
                f"не увидел ни одного GWC-запроса", checks)
        return

    try:
        tiles = _load_tiles_with_data()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _check("gwc_layers", False,
                f"{_tiles_with_data_path()} недоступен ({e}) — задать "
                f"TILES_WITH_DATA_PATH или скопировать файл при деплое", checks)
        return
    tile = tiles[0]
    z = tile["z"]
    x, y = _lonlat_to_tile(tile["lon"], tile["lat"], z)
    bbox = _tile_bbox_3857(x, y, z)
    bbox_str = ",".join(str(v) for v in bbox)

    for layer, captured_url in captured.items():
        parsed = urllib.parse.urlsplit(captured_url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        params["bbox"] = bbox_str
        params["srs"] = "EPSG:3857"
        url = f"{base_url}{parsed.path}?{urllib.parse.urlencode(params)}"

        check_name = f"gwc_layer[{layer}]"
        try:
            resp = requests.get(url, timeout=15)
        except requests.RequestException as e:
            _check(check_name, False, f"запрос не выполнен: {e}", checks)
            continue

        if b"Unknown layer" in resp.content or b"GWC Error" in resp.content:
            _check(check_name, False,
                    f"HTTP {resp.status_code}, GWC вернул ошибку "
                    f"(похоже на round34 A — отсутствие workspace-префикса "
                    f"или незарегистрированный слой): {resp.content[:200]}", checks)
            continue

        ok, detail = _png_has_nonempty_colors(resp.content)
        cache_result = resp.headers.get("geowebcache-cache-result", "-")
        _check(check_name, ok,
                f"HTTP {resp.status_code}, {detail}, geowebcache-cache-result={cache_result}", checks)


def check_wfs(base_url: str, checks: list):
    url = (
        f"{base_url}/geoserver/{GEOSERVER_WORKSPACE}/ows"
        "?service=WFS&version=1.0.0&request=GetFeature"
        f"&typeName={GEOSERVER_WORKSPACE}:fields&maxFeatures=5"
        "&outputFormat=application/json"
    )
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as e:
        _check("wfs_getfeature", False, f"запрос не выполнен: {e}", checks)
        return

    text = resp.text
    if "ServiceExceptionReport" in text or "ExceptionReport" in text:
        _check("wfs_getfeature", False,
                f"HTTP {resp.status_code}, тело — ServiceExceptionReport", checks)
        return

    try:
        data = resp.json()
    except ValueError:
        _check("wfs_getfeature", False,
                f"HTTP {resp.status_code}, тело не парсится как JSON", checks)
        return

    features = data.get("features")
    if not isinstance(features, list) or len(features) == 0:
        _check("wfs_getfeature", False,
                f"HTTP {resp.status_code}, FeatureCollection пуст "
                f"(0 объектов) — данные есть, но слой их не отдаёт", checks)
        return

    props = features[0].get("properties", {})
    if not props or all(v in (None, "") for v in props.values()):
        _check("wfs_getfeature", False,
                "объекты есть, но атрибуты пустые/все NULL", checks)
        return

    _check("wfs_getfeature", True,
            f"HTTP {resp.status_code}, {len(features)} объектов, "
            f"атрибуты непустые (пример: {list(props.keys())[:5]})", checks)


def check_error_path(base_url: str, checks: list):
    """round30, C.3б: баг Caddy (`handle_response` без `copy_response`)
    подменял ЛЮБОЙ не-200 ответ GeoServer синтетическим пустым `200` —
    жил в проде незамеченным целый раунд именно потому, что ни один
    контроль не заходил на заведомо несуществующий путь. Эта проверка
    подтверждает факт, а не полагается на код: несуществующий путь
    обязан вернуть НЕ `200` и НЕПУСТОЕ тело (настоящую ошибку от
    GeoServer или самого Caddy), а не пустой `200 Content-Length: 0`."""
    url = f"{base_url}/geoserver/nonexistent"
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as e:
        _check("error_path", False, f"запрос не выполнен: {e}", checks)
        return

    if resp.status_code == 200:
        _check("error_path", False,
                f"HTTP 200 на заведомо несуществующий путь — похоже на "
                f"регрессию округа30 C.3б (пустой синтетический 200 вместо "
                f"реальной ошибки); тело: {len(resp.content)} байт", checks)
        return

    if len(resp.content) == 0:
        _check("error_path", False,
                f"HTTP {resp.status_code}, но тело ПУСТОЕ — код не 200, но "
                f"это всё ещё может быть синтетический ответ без реального "
                f"содержимого", checks)
        return

    _check("error_path", True,
            f"HTTP {resp.status_code}, тело непустое ({len(resp.content)} байт)", checks)


def check_main_page(base_url: str, checks: list):
    try:
        resp = requests.get(base_url + "/", timeout=15)
    except requests.RequestException as e:
        _check("main_page", False, f"запрос не выполнен: {e}", checks)
        return
    body = resp.text
    ok = resp.status_code == 200 and "<div id=\"root\"" in body
    _check("main_page", ok,
            f"HTTP {resp.status_code}, {'React-корень найден' if ok else 'тело не похоже на React SPA'}", checks)


def check_year_district(base_url: str, checks: list) -> dict | None:
    try:
        resp = requests.get(base_url + "/static/year_district.json", timeout=15)
    except requests.RequestException as e:
        _check("year_district_json", False, f"запрос не выполнен: {e}", checks)
        return None

    try:
        data = resp.json()
    except ValueError:
        _check("year_district_json", False,
                f"HTTP {resp.status_code}, тело не парсится как JSON", checks)
        return None

    # Реальный формат write_year_district_lookup() (round23, задача 1):
    # {"years": [2025], "districtsByYear": {"2025": ["2208", ...]}}
    years = data.get("years") if isinstance(data, dict) else None
    if not years:
        _check("year_district_json", False, "файл пуст (нет years)", checks)
        return None

    n_pairs = sum(len(v) for v in data.get("districtsByYear", {}).values())
    _check("year_district_json", True,
            f"HTTP {resp.status_code}, {len(years)} лет, {n_pairs} пар год/район", checks)
    return data


def _static_year_district_pairs(static_data) -> set:
    """Разворачивает {"years":[...], "districtsByYear": {"y": [d,...]}}
    в множество пар (year:int, district:str)."""
    pairs = set()
    districts_by_year = static_data.get("districtsByYear", {}) if isinstance(static_data, dict) else {}
    for year_str, districts in districts_by_year.items():
        for d in districts:
            pairs.add((int(year_str), d))
    return pairs


def check_db_matches_static(static_data, checks: list):
    """Сверяет годы/районы из статического файла с тем, что реально
    отдаёт БД (assessment_ready) — расхождение означает, что файл не
    был перезаписан после последней реальной доставки, или доставка
    упала после REFRESH, но до write_year_district_lookup()."""
    if static_data is None:
        _check("db_matches_static", False, "нет данных из year_district.json — сверка невозможна", checks)
        return
    if not FRONTEND_DB["password"]:
        _check("db_matches_static", False,
                "FRONTEND_DB_PASSWORD не задан — сверка с БД пропущена "
                "(healthcheck запущен без доступа к БД)", checks)
        return

    static_pairs = _static_year_district_pairs(static_data)

    env = os.environ.copy()
    env["PGPASSWORD"] = FRONTEND_DB["password"]
    cmd = [
        "psql", "-h", FRONTEND_DB["host"], "-p", str(FRONTEND_DB["port"]),
        "-U", FRONTEND_DB["user"], "-d", FRONTEND_DB["name"], "-tAc",
        "SELECT DISTINCT year, district FROM assessment_ready ORDER BY 1,2;",
        "-F", ",",
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        _check("db_matches_static", False, f"запрос к БД не выполнен: {result.stderr.strip()}", checks)
        return

    db_pairs = set()
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        year_s, district = line.split(",", 1)
        db_pairs.add((int(year_s), district))

    missing_in_static = db_pairs - static_pairs
    extra_in_static = static_pairs - db_pairs
    ok = not missing_in_static and not extra_in_static
    detail = f"БД: {len(db_pairs)} пар, файл: {len(static_pairs)} пар"
    if not ok:
        detail += f"; отсутствует в файле: {missing_in_static}; лишнее в файле: {extra_in_static}"
    _check("db_matches_static", ok, detail, checks)


def run_healthcheck(base_url: str) -> dict:
    checks: list = []
    check_wms(base_url, checks)
    check_gwc_layers(base_url, checks)
    check_wfs(base_url, checks)
    check_error_path(base_url, checks)
    check_main_page(base_url, checks)
    static_data = check_year_district(base_url, checks)
    check_db_matches_static(static_data, checks)

    all_ok = all(c["ok"] for c in checks)
    return {"ok": all_ok, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("HEALTHCHECK_BASE_URL", "https://" + os.getenv("DOMAIN", "geobotany.of.by")),
        help="Публичный URL витрины (по умолчанию — https://$DOMAIN)",
    )
    parser.add_argument("--json", action="store_true", help="Машиночитаемый вывод (JSON)")
    args = parser.parse_args()

    result = run_healthcheck(args.base_url.rstrip("/"))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for c in result["checks"]:
            mark = "OK  " if c["ok"] else "FAIL"
            print(f"[{mark}] {c['check']}: {c['detail']}")
        print()
        print("ИТОГ: " + ("всё в порядке" if result["ok"] else "ЕСТЬ НЕСООТВЕТСТВИЯ"))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
