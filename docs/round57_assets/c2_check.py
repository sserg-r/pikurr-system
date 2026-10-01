from rasterio.io import MemoryFile
from rasterio.merge import merge
import rasterio.mask
from src.utils.postclassify import calculate_zonal_stats, clean
from src.services.db import DatabaseService
from src.core.config import settings
FILES = raster_files(); SHP = sheets()
def ref_own(gj, frames):
    """Эталон вне кода ETL: полное маскирование всего растра листа полигоном, merge, хвост calculate_zonal_stats."""
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
    v = u != 255; u = u[v]; c = c[v]; tot = c.sum()
    return {str(int(k)): float(x) for k, x in zip(u, c / tot)} if tot else {}
def mx(a, b): return max(abs(a.get(str(i), 0) - b.get(str(i), 0)) for i in range(6))
db = DatabaseService(settings)
df = db.execute_query("""select nr_user, ST_AsGeoJSON(a.geom) gj, array_agg(r.n10000 order by r.n10000) fr from agrifields a join razgrafka r on ST_Intersects(a.geom, r.geom) group by nr_user, a.geom""")
df['fr'] = df.fr.map(lambda l: [f for f in l if f in FILES])
cnt = df.groupby('nr_user').size(); df = df[df.nr_user.map(cnt) == 1]    # однокомпонентные ключи
multi = df[df.fr.map(len) >= 2]
print('участков на 2+ листах (однокомпонентные ключи):', len(multi))
asc_desc = ref = 0; mxs = []; mref = []; npairs_ref = 0
for r in multi.itertuples():
    fr = list(r.fr); pols = [SHP[f] for f in fr]
    a = calculate_zonal_stats(r.gj, [FILES[f] for f in fr], sheet_polygons=pols)
    d = calculate_zonal_stats(r.gj, [FILES[f] for f in reversed(fr)], sheet_polygons=list(reversed(pols)))
    mxs.append(mx(a, d))
    if npairs_ref < 80:
        mref.append(mx(a, ref_own(r.gj, fr))); npairs_ref += 1
mxs = np.array(mxs); mref = np.array(mref)
print('по возрастанию vs по убыванию: идентичны у', int((mxs == 0).sum()), 'из', len(mxs), '; max|Δ|', float(mxs.max()))
print('оконная маска (ETL) vs полное маскирование (эталон вне ETL), %d участков: идентичны у %d; max|Δ| %.3g' % (len(mref), int((mref < 1e-12).sum()), mref.max()))
