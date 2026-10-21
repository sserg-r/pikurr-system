"""round64, блок C: число наблюдений Sentinel-2 на листах (только чтение GEE).
Запуск: docker exec -i pikurr-system-etl-1 python - < s2obs.py   (ключ GEE берётся из окружения контейнера, не печатается)
Фильтр — ровно как в src/services/gee.py (get_scl_series_url): окно season_window, CLOUDY_PIXEL_PERCENTAGE < 20,
linkCollection(CloudScore+ cs_cdf), SCL=12 где cs_cdf <= 0.80, дневные мозаики по day-of-year."""
import json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/app")
import ee
import numpy as np
import rasterio
from src.core.season import season_window
from src.tasks.usability import UsabilityTask

SEED, N = 64, 50
YEARS = (2023, 2024, 2025, 2026)
USAB = "/data_output/predictions/predictions_usab"

task = UsabilityTask()                       # ee.Initialize (тот же путь, что в шаге 4)
names = sorted(f[:-4] for f in os.listdir(f"{USAB}/2026") if f.endswith(".tif"))
random.seed(SEED)
sheets = sorted(random.sample(names, N))
print(json.dumps({"seed": SEED, "sheets": sheets}), flush=True)

QA, CLEAR, CPP = "cs_cdf", 0.80, 20


def usab_share(name, year):
    with rasterio.open(f"{USAB}/{year}/{name}.tif") as s:
        a = s.read(1)
    return float((a > 0).mean())


def measure(name, year):
    bbox = task.get_trapeze_bbox(name)
    aoi = ee.Geometry.BBox(*bbox)
    fdate = ee.Filter.date(*season_window(year))
    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")

    def update_scl(img):
        scl = img.select("SCL").where(img.select(QA).lte(CLEAR), 12).rename("SCL")
        return img.addBands(scl, overwrite=True)

    img_col = (s2.filterBounds(aoi).filter(fdate)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CPP))
               .linkCollection(cs_plus, [QA]).map(update_scl))
    doi = img_col.toList(img_col.size()).map(lambda img: ee.Image(img).date().getRelative("day", "year"))
    unique_doi = doi.distinct()

    def daily(d):
        day_col = img_col.filter(ee.Filter.dayOfYear(d, ee.Number(d).add(1)))
        return day_col.mosaic().set({"system:index": ee.String(d),
                                     "system:time_start": ee.Image(day_col.first()).get("system:time_start")})

    mosaic_col = ee.ImageCollection(unique_doi.map(daily))
    # ясное наблюдение пикселя = SCL 4 (растительность) или 5 (голая почва) в дневной мозаике — те значения,
    # которые использует calculate_usability_metric
    clear = mosaic_col.select("SCL").map(lambda im: im.eq(4).Or(im.eq(5)).rename("clear")).sum()
    stats = clear.reduceRegion(ee.Reducer.mean(), aoi, scale=100, maxPixels=1e9)
    info = ee.Dictionary({"n_dates": unique_doi.size(), "n_scenes": img_col.size(),
                          "mean_clear": stats.get("clear")}).getInfo()
    return info


def job(args):
    name, year = args
    for attempt in range(5):
        try:
            r = measure(name, year)
            r.update(sheet=name, year=year, usab_share=usab_share(name, year))
            return r
        except Exception as e:                                   # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(4 * (attempt + 1))
    return {"sheet": name, "year": year, "error": err}


t0 = time.time()
with ThreadPoolExecutor(4) as ex:
    for r in ex.map(job, [(n, y) for n in sheets for y in YEARS]):
        print(json.dumps(r, ensure_ascii=False), flush=True)
print(json.dumps({"done_seconds": round(time.time() - t0)}), flush=True)
