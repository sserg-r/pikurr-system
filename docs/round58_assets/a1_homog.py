# Блок A раунда 58: однородность класса 5 внутри участка. Запуск:
#   (echo "LIMIT=None; SHIFT_M=100.0"; cat ../round56_assets/lib.py a1_homog.py) | ssh <стенд> docker exec -i pikurr-system-etl-1 python3 -
# Только чтение (БД: SELECT; растры: open 'r'). Вывод: JSONL, одна строка на (участок), + строка итога.
from skimage.morphology import closing, disk
from skimage.transform import resize
from rasterio.features import sieve, rasterize
from rasterio.warp import reproject, Resampling
from affine import Affine
import time
OLD = '/data_output/predictions/predictions_final/2025_before_round57'
SH = sheets()
from src.services.db import DatabaseService
from src.core.config import settings
db = DatabaseService(settings)
df = db.execute_query("""WITH u AS (SELECT nr_user, CASE WHEN count(*)>1 THEN ST_Multi(ST_Union(geom)) ELSE ST_Multi((array_agg(geom))[1]) END AS geom
  FROM agrifields GROUP BY nr_user)
  SELECT u.nr_user, ST_AsText(u.geom) g, array_agg(r.n10000 ORDER BY r.n10000) frames FROM u JOIN razgrafka r ON ST_Intersects(u.geom, r.geom) GROUP BY u.nr_user, u.geom""")
F = {}; BYSHEET = {}
for i, r in enumerate(df.itertuples()):
    F[r.nr_user] = _wkt.loads(r.g)
    for n in r.frames: BYSHEET.setdefault(n, []).append(r.nr_user)
ids = {k: i + 1 for i, k in enumerate(F)}; NF = len(ids) + 1
VER = ('old', 'new', 'ctrl')
N3 = {v: np.zeros(NF, np.int64) for v in VER}; N5 = {v: np.zeros(NF, np.int64) for v in VER}
DIST = {}
def combined(name):
    arrs = []
    for y in (2023, 2024, 2025):
        p = f'{USAB}/{y}/{name}.tif'
        if os.path.exists(p):
            with rasterio.open(p) as s: arrs.append((s.read(1), s.transform, s.crs))
    if not arrs: return None
    shp = arrs[0][0].shape
    a = [d if d.shape == shp else resize(d, shp, order=0, preserve_range=True, anti_aliasing=False) for d, _, _ in arrs]
    c = np.array(a).any(axis=0); c = closing(c, disk(1)); c = sieve(c.astype(np.uint8), 10, connectivity=4)
    return c, arrs[0][1], arrs[0][2]
def on_canvas(c, ut, ucrs, vt, vcrs, shape, dx_deg):
    out = np.zeros(shape, np.uint8)
    reproject(c.astype(np.uint8), out, src_transform=ut * Affine.translation(-dx_deg / ut.a, 0) if dx_deg else ut, src_crs=ucrs,
              dst_transform=vt, dst_crs=vcrs, resampling=Resampling.nearest)
    return out
names = sorted(raster_files())
if LIMIT: names = names[:LIMIT]
t0 = time.time(); eq_checks = []
for k, n in enumerate(names):
    if n not in SH: continue
    with rasterio.open(f'{VEGET}/{n}.tif') as s: veg = s.read(1); vt = s.transform; vcrs = s.crs
    with rasterio.open(f'{FINAL}/{n}.tif') as s: new = s.read(1)
    with rasterio.open(f'{OLD}/{n}.tif') as s: old = s.read(1)
    comb = combined(n)
    H, W = veg.shape
    # контроль: маска usab сдвинута на SHIFT_M метров на восток (в градусах долготы на широте листа)
    lat = SH[n].centroid.y
    dx = SHIFT_M / (111320.0 * math.cos(math.radians(lat)))
    if comb is None: ctrl = new.copy()
    else:
        m0 = on_canvas(*comb, vt, vcrs, veg.shape, 0.0)
        m1 = on_canvas(*comb, vt, vcrs, veg.shape, dx)
        base = veg.copy(); base[(m0 > 0) & (veg == 3)] = 5
        eq_checks.append(float((base == new).mean()))   # контроль воспроизведения нового итога
        ctrl = veg.copy(); ctrl[(m1 > 0) & (veg == 3)] = 5
    cand = BYSHEET.get(n, [])
    if not cand: continue
    shapes = [(shapely.geometry.mapping(F[c]), ids[c]) for c in cand]
    lab = rasterize(shapes, out_shape=(H, W), transform=vt, fill=0, dtype='int32')
    inside = geometry_mask([shapely.geometry.mapping(SH[n])], out_shape=(H, W), transform=vt, invert=True)
    lab = np.where(inside, lab, 0)
    flat = lab.ravel()
    for v, arr in (('old', old), ('new', new), ('ctrl', ctrl)):
        a = arr.ravel()
        N3[v] += np.bincount(flat[a == 3], minlength=NF)[:NF]
        N5[v] += np.bincount(flat[a == 5], minlength=NF)[:NF]
    # расстояние от представительной точки участка до границы листа, м
    bnd = ea(SH[n]).boundary
    for c in cand:
        d = ea(F[c].representative_point()).distance(bnd)
        DIST[c] = min(DIST.get(c, 1e9), d)
    if k % 50 == 0: print(f'# {k}/{len(names)} {time.time()-t0:.0f}s', file=sys.stderr, flush=True)
for c, i in ids.items():
    print(json.dumps(dict(nr=c, d=DIST.get(c), **{f'{v}3': int(N3[v][i]) for v in VER}, **{f'{v}5': int(N5[v][i]) for v in VER})), flush=True)
print(json.dumps(dict(summary='repro_new', n=len(eq_checks), min=min(eq_checks) if eq_checks else None, mean=float(np.mean(eq_checks)) if eq_checks else None)))
