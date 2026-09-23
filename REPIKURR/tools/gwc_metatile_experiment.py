# Раунд 34, блок C: сравнение суммарного времени отрисовки "экрана" из
# 12 тайлов при разных metaWidthHeight GWC (4x4/2x2/1x1) на СВЕЖИХ
# (не запрошенных ранее) областях. См. docs/round34-raster-gwc.md, C2.
#
# ТОЛЬКО ЭМУЛЯТОР (192.168.251.190) — скрипт многократно переключает
# metaWidthHeight слоя REST-вызовом и генерирует MISS-нагрузку
# намеренно; на VPS это меняло бы боевую конфигурацию кэша без
# согласования (см. CLAUDE.md, "не менять controlflow.properties" по
# духу — сюда же).
#
# Запуск (на эмуляторе, с доступом к секрету):
#   scp docs/round32_assets/tiles_with_data.json 192.168.251.190:/tmp/
#   ssh 192.168.251.190 'set -a; source ~/repikurr/.env; set +a; \
#     python3 /path/to/gwc_metatile_experiment.py'
#
# После прогона обязательно вернуть metaWidthHeight к боевому значению
# (4x4) — сам скрипт этого не делает, см. docs/round34-raster-gwc.md, C2
# для готовой команды восстановления и проверки.

import json, math, random, time, os, sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GEOSERVER_ADMIN_PASSWORD = os.environ['GEOSERVER_ADMIN_PASSWORD']
BASE_GWC = "http://localhost:8090/geoserver/gwc/service/wms"
REST_LAYER = "http://localhost:8090/geoserver/gwc/rest/layers/pikurr:image_assessment.xml"
LAYER = "pikurr:image_assessment"
ORIGIN = 20037508.342789244
Z = 16

TILES_PATH = os.environ.get('TILES_PATH', '/tmp/tiles_with_data.json')
tiles = json.load(open(TILES_PATH))

def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y

def tile_bbox(x, y, z):
    n = 2 ** z
    tile_size = 2 * ORIGIN / n
    minx = -ORIGIN + x * tile_size
    maxx = minx + tile_size
    maxy = ORIGIN - y * tile_size
    miny = maxy - tile_size
    return [minx, miny, maxx, maxy]

def set_metawidthheight(w, h):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<GeoServerLayer>
  <enabled>true</enabled>
  <name>{LAYER}</name>
  <mimeFormats><string>image/png</string></mimeFormats>
  <gridSubsets><gridSubset><gridSetName>EPSG:900913</gridSetName></gridSubset></gridSubsets>
  <metaWidthHeight><int>{w}</int><int>{h}</int></metaWidthHeight>
  <expireCache>0</expireCache>
  <expireClients>86400</expireClients>
  <gutter>0</gutter>
</GeoServerLayer>"""
    req = urllib.request.Request(REST_LAYER, data=xml.encode(), method='PUT')
    req.add_header('Content-Type', 'text/xml')
    import base64
    auth = base64.b64encode(f"admin:{GEOSERVER_ADMIN_PASSWORD}".encode()).decode()
    req.add_header('Authorization', f'Basic {auth}')
    r = urllib.request.urlopen(req, timeout=15)
    assert r.status in (200, 201), r.status

def fetch(bbox):
    q = {
        "service": "WMS", "request": "GetMap", "format": "image/png", "transparent": "true",
        "version": "1.1.1", "tiled": "true", "width": "256", "height": "256", "srs": "EPSG:3857",
        "bbox": ",".join(str(v) for v in bbox), "layers": LAYER, "styles": "",
    }
    import urllib.parse
    url = BASE_GWC + "?" + urllib.parse.urlencode(q)
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(url, timeout=20)
        body = r.read()
        dt = time.monotonic() - t0
        cache = r.headers.get('geowebcache-cache-result', '?')
        return dt, cache, r.status
    except urllib.error.HTTPError as e:
        dt = time.monotonic() - t0
        return dt, e.headers.get('geowebcache-cache-result', '?'), e.code

# 9 непересекающихся свежих областей по 4x3=12 тайлов, взятых от разных
# центроидов полей из tiles_with_data.json (гарантированно в зоне покрытия
# данными, между собой не пересекаются на z=16 — сдвиг центроидов в
# исходном файле друг от друга кратно больше 4 тайлов z=16).
areas = []
for t in tiles[:9]:
    x0, y0 = lonlat_to_tile(t['lon'], t['lat'], Z)
    block = [tile_bbox(x0 + dx, y0 + dy, Z) for dy in range(3) for dx in range(4)]
    areas.append(block)

configs = [(4, 4), (2, 2), (1, 1)] * 3  # 3 повтора на каждый размер метатайла
random.seed(42)
schedule = list(zip(configs, areas))
random.shuffle(schedule)

print("порядок прогона (перемешан):", [c for c, _ in schedule])

results = []
for (mw, mh), block in schedule:
    set_metawidthheight(mw, mh)
    time.sleep(0.5)  # дать GWC подхватить конфиг

    first_dt, first_cache, first_code = fetch(block[0])

    with ThreadPoolExecutor(max_workers=6) as ex:
        t_screen0 = time.monotonic()
        futs = [ex.submit(fetch, b) for b in block[1:]]
        rest = [f.result() for f in futs]
        screen_total = time.monotonic() - t_screen0

    full_screen_time = first_dt + screen_total  # первый тайл последовательно, затем остальные 11 параллельно — имитация реальной загрузки (первый видимый тайл важен отдельно, остальные догружаются параллельно)
    rest_codes_ok = all(c == 200 for _, _, c in rest)
    results.append({
        "metatile": f"{mw}x{mh}",
        "first_tile_ms": round(first_dt * 1000),
        "first_cache": first_cache,
        "screen_12_tiles_total_ms": round(full_screen_time * 1000),
        "rest_all_200": rest_codes_ok,
        "rest_cache_results": [c for _, c, _ in rest],
    })
    print(results[-1])

print("\n--- ИТОГ (все замеры, порядок выполнения — см. выше) ---")
for r in results:
    print(r)
