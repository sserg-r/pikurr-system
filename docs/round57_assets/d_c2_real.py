# C2 на реальном результате: 200 случайных участков на 2+ листах — пересчёт вне кода ETL (полное маскирование листов полигонами, листы в ОБРАТНОМ порядке) против assessment.stats
from rasterio.io import MemoryFile
from rasterio.merge import merge
import rasterio.mask
from src.utils.postclassify import clean
from src.services.db import DatabaseService
from src.core.config import settings
FILES = raster_files(); SHP = sheets()
def ref_own(gj, frames):
    dss, mfs = [], []
    for f in frames:
        with rasterio.open(FILES[f]) as s: data = s.read(1); meta = s.meta.copy(); t = s.transform
        inp = geometry_mask([shapely.geometry.mapping(SHP[f])], out_shape=data.shape, transform=t, invert=True)
        data[~inp] = 255; meta.update(nodata=255)
        mf = MemoryFile(); ds = mf.open(**meta); ds.write(data, 1); dss.append(ds); mfs.append(mf)
    meta = dss[0].meta; d, tr = merge(dss, nodata=255); meta.update(transform=tr, width=d.shape[2], height=d.shape[1], nodata=255)
    with MemoryFile() as mem:
        with mem.open(**meta) as src:
            src.write(d); out, _ = rasterio.mask.mask(src, [json.loads(gj)], crop=True, filled=False, pad=True, pad_width=2, nodata=255)
    [x.close() for x in dss]; [m.close() for m in mfs]
    cl = clean(out); u, c = np.unique(cl, return_counts=True)
    if hasattr(u, 'mask'): mk = u.mask; u = u.data[~mk]; c = c[~mk]
    v = u != 255; u = u[v]; c = c[v]
    return {str(int(k)): float(x) for k, x in zip(u, c / c.sum())} if len(c) else {}
db = DatabaseService(settings)
df = db.execute_query("""WITH u AS (SELECT nr_user, CASE WHEN count(*)>1 THEN ST_Multi(ST_Union(geom)) ELSE ST_Multi((array_agg(geom))[1]) END geom FROM agrifields GROUP BY nr_user)
  SELECT u.nr_user, ST_AsGeoJSON(u.geom) gj, array_agg(r.n10000) fr, (SELECT stats::text FROM assessment a WHERE a.fid_ext = u.nr_user::bigint AND a.year = 2025) st
  FROM u JOIN razgrafka r ON ST_Intersects(u.geom, r.geom) GROUP BY u.nr_user, u.geom""")
df['fr'] = df.fr.map(lambda l: sorted(f for f in l if f in FILES))
multi = df[df.fr.map(len) >= 2]
print('участков на 2+ листах:', len(multi), '; строк assessment всего:', int(db.execute_query('select count(*) c from assessment').c[0]), '; ключей agrifields:', int(db.execute_query('select count(distinct nr_user) c from agrifields').c[0]))
samp = multi.sample(200, random_state=57)
eq = eqr = 0; mxd = mxr = 0.0; bad = []
for r in samp.itertuples():
    got = json.loads(r.st)
    ref = ref_own(r.gj, list(r.fr)); refr = ref_own(r.gj, list(reversed(r.fr)))   # порядок как в ETL (по имени) и обратный
    d = max(abs(ref.get(str(i), 0) - got.get(str(i), 0)) for i in range(6)); dr = max(abs(refr.get(str(i), 0) - got.get(str(i), 0)) for i in range(6))
    mxd = max(mxd, d); mxr = max(mxr, dr); eq += d < 1e-9; eqr += dr < 1e-9
    if d >= 1e-9: bad.append((r.nr_user, round(d, 6)))
print('200 участков, эталон вне ETL (полное маскирование листов, порядок листов по имени): совпали %d; max|Δ| %.3g; расхождения %s' % (eq, mxd, bad[:5]))
print('то же, листы в ОБРАТНОМ порядке: совпали %d; max|Δ| %.3g (сетка merge задаётся первым источником; ETL порядок фиксирует)' % (eqr, mxr))
