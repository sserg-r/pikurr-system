"""Web Mercator (EPSG:3857) <-> XYZ-тайл математика для замеров GWC/WMS.

round35, блок A1: эта математика была независимо переизобретена как
минимум дважды — round32 (`/tmp/round32_tile_math.py`, не коммитился) и
round34 (инлайн-python внутри Bash-эвристик для A1.4, C1, C2 отчёта
round34) — с одинаковым результатом, но каждый раз заново. Единственная
версия отсюда — использовать в последующих раундах вместо повторного
изобретения; расхождение с round32 проверено на тех же входных lon/lat
из `docs/round32_assets/tiles_with_data.json` (см. `if __name__ == ...`
ниже) — совпадает по всем 20 записям.

Использование как модуля:
    from tile_math import lonlat_to_tile, tile_bbox_3857
    x, y = lonlat_to_tile(lon, lat, z)
    bbox = tile_bbox_3857(x, y, z)  # [minx, miny, maxx, maxy] в EPSG:3857

Использование как CLI (одна точка):
    python3 tile_math.py --lon 26.6119 --lat 55.4629 --z 13
"""
import math

ORIGIN = 20037508.342789244  # pi * R, R = 6378137.0 (WGS84 sphere)


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_bbox_3857(x, y, z):
    n = 2 ** z
    tile_size = 2 * ORIGIN / n
    minx = -ORIGIN + x * tile_size
    maxx = minx + tile_size
    maxy = ORIGIN - y * tile_size
    miny = maxy - tile_size
    return [minx, miny, maxx, maxy]


def lonlat_to_bbox_3857(lon, lat, z):
    x, y = lonlat_to_tile(lon, lat, z)
    return tile_bbox_3857(x, y, z)


def tiles_overlap(bbox_a, bbox_b):
    """True, если два bbox (EPSG:3857, [minx,miny,maxx,maxy]) пересекаются.

    round35, блок D: используется, чтобы программно (не на глаз)
    подтверждать непересекаемость областей эксперимента с метатайлами —
    round34 C2 полагался на визуальный подбор координат.
    """
    ax0, ay0, ax1, ay1 = bbox_a
    bx0, by0, bx1, by1 = bbox_b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


if __name__ == "__main__":
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--z", type=int, default=13)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="сверить с docs/round32_assets/tiles_with_data.json (round32, z=13)",
    )
    args = parser.parse_args()

    if args.self_check:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "..", "docs", "round32_assets", "tiles_with_data.json")
        tiles = json.load(open(path))
        mismatches = 0
        for t in tiles:
            x, y = lonlat_to_tile(t["lon"], t["lat"], t["z"])
            bbox = tile_bbox_3857(x, y, t["z"])
            ok = (x, y) == (t["tx"], t["ty"]) and all(
                abs(a - b) < 1e-3 for a, b in zip(bbox, t["bbox_3857"])
            )
            if not ok:
                mismatches += 1
                print(f"MISMATCH lon={t['lon']} lat={t['lat']}: got tx={x},ty={y},bbox={bbox}")
        print(f"{len(tiles) - mismatches}/{len(tiles)} совпало с docs/round32_assets/tiles_with_data.json")
    elif args.lon is not None and args.lat is not None:
        x, y = lonlat_to_tile(args.lon, args.lat, args.z)
        bbox = tile_bbox_3857(x, y, args.z)
        print(json.dumps({"tx": x, "ty": y, "z": args.z, "bbox_3857": bbox}))
    else:
        parser.print_help()
