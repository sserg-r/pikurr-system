"""Прогрев тайлового кэша GWC обычными HTTP GetMap-запросами (round36, блок B).

Независимо от исхода расследования внутреннего засева GWC (round35 C2,
round36 A): внутренний засев уже один раз отрапортовал успех при
недосеянном кэше (см. docs/round36-seeding-fix.md, блок A), поэтому
нужен путь прогрева, где виден КАЖДЫЙ ответ по содержимому — тем же
эндпоинтом, что использует фронтенд (`/geoserver/gwc/service/wms` с
`tiled=true`), а не только "скрипт завершился без ошибки".

Строит список тайлов по сетке GWC (метатайл-грид не используется —
здесь каждый тайл запрашивается отдельно, как это делает браузер) для
заданной bbox/диапазона зумов, опрашивает N потоками, пишет NDJSON-лог
по каждому ответу (код, размер, `geowebcache-cache-result`), умеет
продолжать с места остановки (--resume) и завершаться по SIGINT/SIGTERM
без потери прогресса.

Критерий завершения прогрева — НЕ "скрипт вышел с кодом 0", а
контрольный повторный проход тем же диапазоном БЕЗ --resume: он снова
запрашивает каждый тайл и печатает итоговую долю `hit` в сводке JSON —
это и есть проверка по содержимому, а не просто факт завершения скрипта.

Использование:
    python3 gwc_http_seed.py --base-url https://geobotany.of.by \
        --layer pikurr:image_assessment --zoom-start 9 --zoom-stop 13 \
        --threads 4 --log /tmp/seed_progress.ndjson

    # контрольный проход (та же команда без --resume, свежий --log):
    python3 gwc_http_seed.py --base-url ... --layer ... \
        --zoom-start 9 --zoom-stop 13 --log /tmp/seed_verify.ndjson
    # смотреть "hit"/("hit"+"miss") в итоговой JSON-строке на stdout
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tile_math import tile_bbox_3857, tile_range_for_bbox_3857  # noqa: E402

MIN_NONEMPTY_BYTES = 2048  # округление "правила непустых тайлов" (round32)

_stop = threading.Event()


def _handle_signal(signum, frame):
    print(f"\n[gwc_http_seed] получен сигнал {signum} — завершаю после текущих запросов, прогресс сохранён", file=sys.stderr)
    _stop.set()


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def build_tile_list(bbox_3857, zoom_start, zoom_stop):
    tiles = []
    for z in range(zoom_start, zoom_stop + 1):
        tx_min, tx_max, ty_min, ty_max = tile_range_for_bbox_3857(bbox_3857, z)
        for tx in range(tx_min, tx_max + 1):
            for ty in range(ty_min, ty_max + 1):
                tiles.append((z, tx, ty))
    return tiles


def tile_url(base_url, layer, z, tx, ty):
    bbox = tile_bbox_3857(tx, ty, z)
    params = {
        "service": "WMS",
        "request": "GetMap",
        "layers": layer,
        "styles": "",
        "format": "image/png",
        "transparent": "true",
        "version": "1.1.1",
        "tiled": "true",
        "width": "256",
        "height": "256",
        "srs": "EPSG:3857",
        "bbox": ",".join(f"{v:.10f}" for v in bbox),
    }
    return f"{base_url.rstrip('/')}/geoserver/gwc/service/wms?" + urllib.parse.urlencode(params)


def load_done_set(log_path):
    done = set()
    if not os.path.exists(log_path):
        return done
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ok"):
                done.add((rec["z"], rec["tx"], rec["ty"]))
    return done


def fetch_one(session, base_url, layer, z, tx, ty, auth, timeout_s):
    url = tile_url(base_url, layer, z, tx, ty)
    t0 = time.monotonic()
    try:
        resp = session.get(url, auth=auth, timeout=timeout_s)
        elapsed = time.monotonic() - t0
        content_len = len(resp.content)
        cache_result = resp.headers.get("geowebcache-cache-result", "")
        is_png = resp.content[:8] == b"\x89PNG\r\n\x1a\n"
        ok = resp.status_code == 200 and is_png and content_len >= 67  # 67B = минимальный валидный PNG
        return {
            "z": z, "tx": tx, "ty": ty,
            "status": resp.status_code,
            "bytes": content_len,
            "cache_result": cache_result,
            "elapsed_s": round(elapsed, 3),
            "ok": ok,
            "ts": time.time(),
        }
    except requests.RequestException as e:
        return {
            "z": z, "tx": tx, "ty": ty,
            "status": None, "bytes": 0, "cache_result": "",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "ok": False, "error": str(e), "ts": time.time(),
        }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True)
    p.add_argument("--layer", required=True, help="полное имя pikurr:слой")
    p.add_argument("--bbox", help="minx,miny,maxx,maxy в EPSG:3857; по умолчанию берётся из GWC REST layer config")
    p.add_argument("--zoom-start", type=int, required=True)
    p.add_argument("--zoom-stop", type=int, required=True)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--log", required=True, help="NDJSON-лог прогресса (используется и для --resume)")
    p.add_argument("--resume", action="store_true", help="пропустить тайлы, уже отмеченные ok=true в --log")
    p.add_argument("--user", default=os.environ.get("GEOSERVER_USER"))
    p.add_argument("--password", default=os.environ.get("GEOSERVER_PASSWORD"))
    p.add_argument("--timeout-s", type=float, default=30.0)
    args = p.parse_args()

    auth = (args.user, args.password) if args.user else None

    if args.bbox:
        bbox = [float(v) for v in args.bbox.split(",")]
    else:
        resp = requests.get(
            f"{args.base_url.rstrip('/')}/geoserver/gwc/rest/layers/{args.layer}.json", auth=auth, timeout=30,
        )
        resp.raise_for_status()
        gridsubsets = resp.json()["GeoServerLayer"]["gridSubsets"]
        extent = next(g["extent"]["coords"] for g in gridsubsets if g["gridSetName"] == "EPSG:900913")
        bbox = extent
        print(f"[gwc_http_seed] bbox взят из GWC REST layer config: {bbox}", file=sys.stderr)

    tiles = build_tile_list(bbox, args.zoom_start, args.zoom_stop)
    print(f"[gwc_http_seed] построено {len(tiles)} тайлов для z{args.zoom_start}-{args.zoom_stop}", file=sys.stderr)

    done = load_done_set(args.log) if args.resume else set()
    if done:
        print(f"[gwc_http_seed] --resume: пропускаю {len(done)} уже успешных тайлов из {args.log}", file=sys.stderr)
    todo = [t for t in tiles if t not in done]

    log_mode = "a" if (args.resume and os.path.exists(args.log)) else "w"
    log_lock = threading.Lock()
    counters = {"ok": 0, "fail": 0, "hit": 0, "miss": 0, "empty_or_small": 0}

    session = requests.Session()

    with open(args.log, log_mode) as logf:
        def worker(z, tx, ty):
            if _stop.is_set():
                return None
            rec = fetch_one(session, args.base_url, args.layer, z, tx, ty, auth, args.timeout_s)
            with log_lock:
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                logf.flush()
                if rec["ok"]:
                    counters["ok"] += 1
                else:
                    counters["fail"] += 1
                cr = rec.get("cache_result", "").upper()
                if cr == "HIT":
                    counters["hit"] += 1
                elif cr == "MISS":
                    counters["miss"] += 1
                if rec.get("bytes", 0) < MIN_NONEMPTY_BYTES:
                    counters["empty_or_small"] += 1
            return rec

        t_start = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            futures = [pool.submit(worker, z, tx, ty) for (z, tx, ty) in todo]
            n_total = len(futures)
            n_reported = 0
            for fut in as_completed(futures):
                fut.result()
                n_reported += 1
                if n_reported % 500 == 0 or n_reported == n_total:
                    elapsed = time.monotonic() - t_start
                    print(
                        f"[gwc_http_seed] {n_reported}/{n_total} "
                        f"ok={counters['ok']} fail={counters['fail']} "
                        f"hit={counters['hit']} miss={counters['miss']} "
                        f"мелких(<{MIN_NONEMPTY_BYTES}B)={counters['empty_or_small']} "
                        f"t={elapsed:.1f}s",
                        file=sys.stderr,
                    )
                if _stop.is_set():
                    break

    elapsed_total = time.monotonic() - t_start
    small_frac = counters["empty_or_small"] / max(1, counters["ok"] + counters["fail"])
    print(
        json.dumps({
            "requested": n_total,
            "processed": n_reported,
            "ok": counters["ok"],
            "fail": counters["fail"],
            "hit": counters["hit"],
            "miss": counters["miss"],
            "small_or_empty_fraction": round(small_frac, 4),
            "elapsed_s": round(elapsed_total, 2),
            "interrupted": _stop.is_set(),
        }, ensure_ascii=False),
    )
    if small_frac > 0.20:
        print(
            f"[gwc_http_seed] ПРЕДУПРЕЖДЕНИЕ: доля мелких/пустых ответов {small_frac:.1%} > 20% "
            f"— правило непустых тайлов (round32) нарушено, прогрев не считать валидным без разбора причины",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
