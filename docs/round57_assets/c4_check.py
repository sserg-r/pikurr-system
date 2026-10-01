exec(open('/dev/null').read())
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
    cl = clean(out); u, c = np.unique(cl, return_counts=True)
    if hasattr(u, 'mask'): mk = u.mask; u = u.data[~mk]; c = c[~mk]
    v = u != 255; u = u[v]; c = c[v]
    return {str(int(k)): float(x) for k, x in zip(u, c / c.sum())}
db = DatabaseService(settings)
# независимая сборка геометрии: объединение частей средствами shapely (не SQL ETL)
df = db.execute_query("select ogc_fid, ST_AsBinary(geom) w from agrifields where nr_user='22490000030364' order by ogc_fid")
from shapely import wkb
parts = [wkb.loads(bytes(r.w)) for r in df.itertuples()]
U = shapely.union_all(parts)
if U.geom_type == 'Polygon': U = shapely.geometry.MultiPolygon([U])
frames = sorted(n for n, p in SHP.items() if n in FILES and p.intersects(U))
print('части:', len(parts), 'площади (га):', [round(area_ha(p), 4) for p in parts], 'листов:', frames)
st_union = ref_own(json.dumps(shapely.geometry.mapping(U)), frames)
st_part1 = ref_own(json.dumps(shapely.geometry.mapping(shapely.geometry.MultiPolygon([parts[0]]) if parts[0].geom_type == 'Polygon' else parts[0])), sorted(n for n, p in SHP.items() if n in FILES and p.intersects(parts[0])))
st_part2 = ref_own(json.dumps(shapely.geometry.mapping(shapely.geometry.MultiPolygon([parts[1]]) if parts[1].geom_type == 'Polygon' else parts[1])), sorted(n for n, p in SHP.items() if n in FILES and p.intersects(parts[1])))
print('эталон по объединению:', json.dumps(st_union)); print('часть 1:', json.dumps(st_part1)); print('часть 2:', json.dumps(st_part2))
