# A3: вариант «свой лист». Только расчёт, stdout. Копия хвоста calculate_zonal_stats (postclassify.py) + маскирование листа его полигоном.
from multiprocessing import Pool
from collections import OrderedDict
import random
from rasterio.io import MemoryFile
from rasterio.merge import merge
import rasterio.mask
from src.utils.postclassify import calculate_zonal_stats, clean
SHP = None; CACHE = OrderedDict(); MFS = {}
def masked_ds(name):
    if name in CACHE:
        CACHE.move_to_end(name); return CACHE[name]
    with rasterio.open(FILES[name]) as s:
        data = s.read(1); meta = s.meta.copy(); t = s.transform
    h, w = data.shape
    inp = geometry_mask([shapely.geometry.mapping(SHP[name])], out_shape=(h, w), transform=t, invert=True)
    data[~inp] = 255
    meta.update(nodata=255)
    mf = MemoryFile(); ds = mf.open(**meta); ds.write(data, 1)
    CACHE[name] = ds; MFS[name] = mf
    while len(CACHE) > 6:
        k, v = CACHE.popitem(last=False); v.close(); MFS.pop(k).close()
    return ds
def tail(srcs, geom_json_str):
    shapes = [json.loads(geom_json_str)]
    meta = srcs[0].meta
    data, transform = merge(srcs, nodata=255)
    meta.update(transform=transform, width=data.shape[2], height=data.shape[1], nodata=255)
    with MemoryFile() as memfile:
        with memfile.open(**meta) as src:
            src.write(data)
            out_image, _ = rasterio.mask.mask(src, shapes, crop=True, filled=False, pad=True, pad_width=2, nodata=255)
    cleaned = clean(out_image)
    unique, counts = np.unique(cleaned, return_counts=True)
    if hasattr(unique, 'mask'):
        mk = unique.mask; unique = unique.data[~mk]; counts = counts[~mk]
    vi = unique != 255; unique = unique[vi]; counts = counts[vi]
    total = np.sum(counts)
    if total == 0: return {}
    return {str(int(k)): float(v) for k, v in zip(unique, counts / total)}
def work(task):
    nr, gj, frames, variants = task
    out = {'nr': nr, 'nfr': len(frames)}
    fr = sorted(frames)
    try:
        if 'own' in variants:
            out['own'] = tail([masked_ds(f) for f in fr], gj)
        if 'asc' in variants:
            out['asc'] = calculate_zonal_stats(gj, [FILES[f] for f in fr])
        if 'desc' in variants:
            out['desc'] = calculate_zonal_stats(gj, [FILES[f] for f in reversed(fr)])
    except Exception as e:
        out['err'] = repr(e)
    return out
if __name__ == '__main__':
    from src.services.db import DatabaseService
    from src.core.config import settings
    SHP = sheets(); FILES = raster_files()
    db = DatabaseService(settings)
    df = db.execute_query("""select nr_user, ST_AsGeoJSON(a.geom) gj, array_agg(r.n10000) fr
                             from agrifields a join razgrafka r on ST_Intersects(a.geom, r.geom) group by nr_user, a.geom""")
    cnt = df.groupby('nr_user').size()
    df = df[df.nr_user.map(cnt) == 1]                                    # без многочастных nr_user (см. отчёт)
    df['fr'] = df.fr.map(lambda l: [f for f in l if f in FILES])
    multi = df[df.fr.map(len) >= 2]; single = df[df.fr.map(len) == 1]
    random.seed(56)
    sm = set(random.sample(list(multi.nr_user), 600)); ss = set(random.sample(list(single.nr_user), 600))
    tasks = []
    for r in multi.itertuples():
        tasks.append((r.nr_user, r.gj, list(r.fr), ('own', 'asc', 'desc') if r.nr_user in sm else ('own',)))
    for r in single.itertuples():
        if r.nr_user in ss: tasks.append((r.nr_user, r.gj, list(r.fr), ('own', 'asc')))
    tasks.sort(key=lambda t: tuple(sorted(t[2])))
    print('TASKS', len(tasks), 'multi', len(multi), 'single', len(single), file=sys.stderr, flush=True)
    with Pool(14) as pool:
        for r in pool.imap(work, tasks, chunksize=16):
            print(json.dumps(r), flush=True)
