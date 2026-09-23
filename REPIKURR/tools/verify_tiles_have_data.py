"""Проверка "правила непустых тайлов" (CLAUDE.md) для набора bbox.

round35, блок A1: консолидация повторявшегося паттерна — round32
(`/tmp/round32_verify_tiles.py`, не коммитился) и round34 (инлайн-curl
циклы в A1.4/C1 отчёта round34) делали одно и то же вручную заново.

Использование:
    python3 verify_tiles_have_data.py \
        --base-url https://geobotany.of.by \
        --layer pikurr:image_assessment \
        --via gwc \
        --tiles ../../docs/round32_assets/tiles_with_data.json \
        --min-bytes 2048

`--via` — `gwc` (`/geoserver/gwc/service/wms`, слой ОБЯЗАН быть с
workspace-префиксом, round34 A) или `wms` (`/geoserver/pikurr/wms`).
Печатает per-tile результат и итоговую долю ответов < `--min-bytes`
(порог из CLAUDE.md — если выше 20%, замер дальше считать невалидным).
"""
import argparse
import json
import urllib.parse
import urllib.request

from tile_math import lonlat_to_tile, tile_bbox_3857


def fetch(base_url, via, layer, bbox):
    path = "/geoserver/gwc/service/wms" if via == "gwc" else "/geoserver/pikurr/wms"
    q = {
        "service": "WMS", "request": "GetMap", "format": "image/png", "transparent": "true",
        "version": "1.1.1", "width": "256", "height": "256", "srs": "EPSG:3857",
        "bbox": ",".join(str(v) for v in bbox), "layers": layer, "styles": "",
    }
    if via == "gwc":
        q["tiled"] = "true"
    url = base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(q)
    try:
        r = urllib.request.urlopen(url, timeout=15)
        body = r.read()
        return r.status, len(body), r.headers.get("geowebcache-cache-result", "-")
    except urllib.error.HTTPError as e:
        return e.code, 0, e.headers.get("geowebcache-cache-result", "-")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True)
    p.add_argument("--layer", required=True)
    p.add_argument("--via", choices=["gwc", "wms"], default="gwc")
    p.add_argument("--tiles", default="../../docs/round32_assets/tiles_with_data.json")
    p.add_argument("--z", type=int, default=None, help="пересчитать bbox на другом зуме (по умолчанию — z из файла, обычно 13)")
    p.add_argument("--min-bytes", type=int, default=2048)
    args = p.parse_args()

    tiles = json.load(open(args.tiles))
    empty = 0
    for t in tiles:
        z = args.z or t["z"]
        x, y = lonlat_to_tile(t["lon"], t["lat"], z)
        bbox = tile_bbox_3857(x, y, z)
        status, size, cache = fetch(args.base_url, args.via, args.layer, bbox)
        is_empty = status != 200 or size < args.min_bytes
        if is_empty:
            empty += 1
        print(f"lon={t['lon']:.4f} lat={t['lat']:.4f} z={z} status={status} size={size} cache={cache} {'EMPTY' if is_empty else 'ok'}")

    frac = empty / len(tiles) if tiles else 0
    print(f"\n{empty}/{len(tiles)} пустых/маленьких (< {args.min_bytes} байт) — {frac:.0%}")
    if frac > 0.2:
        print("ВНИМАНИЕ: доля выше 20% — правило CLAUDE.md считает такой замер НЕвалидным для оценки скорости.")


if __name__ == "__main__":
    main()
