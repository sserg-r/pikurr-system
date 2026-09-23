"""round35, блок C1: распределение зумов, которые реально запрашивает
фронтенд — по `all_tile_requests.json`, который пишет `smoke.mjs`
(REPIKURR/tools/smoke/smoke.mjs) за один прогон сценария. Zoom
вычисляется из ширины bbox тайла (все тайлы — 256×256, ширина bbox
однозначно определяет z в Web Mercator).

Использование:
    python3 analyze_zoom_usage.py tools/smoke/all_tile_requests.json
"""
import json
import math
import sys
from collections import Counter

ORIGIN = 20037508.342789244


def bbox_to_zoom(bbox_str):
    minx, miny, maxx, maxy = (float(v) for v in bbox_str.split(","))
    width = maxx - minx
    n = (2 * ORIGIN) / width
    z = round(math.log2(n))
    return z


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "tools/smoke/all_tile_requests.json"
    reqs = json.load(open(path))

    by_layer_zoom = Counter()
    for r in reqs:
        z = bbox_to_zoom(r["bbox"])
        by_layer_zoom[(r["layer"], z)] += 1

    zooms_all = Counter()
    for (layer, z), n in by_layer_zoom.items():
        zooms_all[z] += n

    print(f"Всего тайловых запросов: {len(reqs)}")
    print(f"\nПо слою и зуму:")
    for (layer, z), n in sorted(by_layer_zoom.items()):
        print(f"  {layer:30s} z={z:2d}  {n:4d} запросов")

    print(f"\nРаспределение по зуму (все слои):")
    for z in sorted(zooms_all):
        print(f"  z={z:2d}: {zooms_all[z]:4d}")

    if zooms_all:
        print(f"\nmin_zoom={min(zooms_all)} max_zoom={max(zooms_all)}")


if __name__ == "__main__":
    main()
