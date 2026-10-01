from skimage.morphology import closing, disk
from skimage.transform import resize
from rasterio.features import sieve
from rasterio.warp import reproject, Resampling
import hashlib
OUT = '/tmp/pikurr_r57'   # смонтировано не будет; пути к выходам передаются каталогами ниже
NAMES = ['N-35-34-В-а-4', 'N-35-34-В-а-3', 'N-35-34-В-б-3']
rng = np.random.default_rng(57)
def combined(name):
    arrs = []
    for y in (2023, 2024, 2025):
        p = f'{USAB}/{y}/{name}.tif'
        if os.path.exists(p):
            with rasterio.open(p) as s: arrs.append((s.read(1), s.transform))
    shp = arrs[0][0].shape
    a = [d if d.shape == shp else resize(d, shp, order=0, preserve_range=True, anti_aliasing=False) for d, _ in arrs]
    c = np.array(a).any(axis=0); c = closing(c, disk(1)); c = sieve(c.astype(np.uint8), 10, connectivity=4)
    return c, arrs[0][1]
SH = sheets()
res = []
for n in NAMES:
    with rasterio.open(f'{VEGET}/{n}.tif') as s: veg = s.read(1); vt = s.transform
    fin = {}
    for tag in ('old', 'new'):
        with rasterio.open(f'/cmp_{tag}/2025/{n}.tif') as s: fin[tag] = s.read(1)
    with rasterio.open(f'{FINAL}/{n}.tif') as s: real = s.read(1)
    c, ut = combined(n)
    H, W = veg.shape
    inv = ~ut
    def mask_at(rows, cols):
        lon, lat = vt * (cols + 0.5, rows + 0.5)
        cc, rr = inv * (lon, lat)
        rr = np.floor(rr).astype(int); cc = np.floor(cc).astype(int)
        ok = (rr >= 0) & (rr < c.shape[0]) & (cc >= 0) & (cc < c.shape[1])
        m = np.zeros(len(rows), bool); m[ok] = c[rr[ok], cc[ok]] > 0
        return m
    r = dict(name=n, old_equals_real_final=bool((fin['old'] == real).all()))
    for tag in ('old', 'new'):
        rr, cc = np.nonzero(fin[tag] == 5); k = rng.choice(len(rr), 2000, replace=False)
        m = mask_at(rr[k], cc[k]); r[f'{tag}_class5_with_mask'] = float(m.mean())
        # класс 3 в точках, где veget==3 и маска>0 (внутри охвата usab): должен быть 5
        ys, xs = np.nonzero(veg == 3); sel = rng.choice(len(ys), 400000, replace=False); ys, xs = ys[sel], xs[sel]
        mm = mask_at(ys, xs); ys, xs = ys[mm][:2000], xs[mm][:2000]
        r[f'{tag}_veget3_mask_not5'] = int((fin[tag][ys, xs] != 5).sum()); r[f'{tag}_n_pts_veget3_mask'] = int(len(ys))
    # доли несовпадения внутри полигона
    inpoly = geometry_mask([shapely.geometry.mapping(SH[n])], out_shape=(H, W), transform=vt, invert=True)
    r['final_class5_differs_old_new_in_poly'] = float(((fin['old'] == 5) != (fin['new'] == 5))[inpoly].mean())
    r['final_any_class_differs_old_new_in_poly'] = float((fin['old'] != fin['new'])[inpoly].mean())
    st = resize(c, veg.shape, preserve_range=True) > 0
    geo = np.zeros(veg.shape, np.uint8)
    reproject(c.astype(np.uint8), geo, src_transform=ut, src_crs='EPSG:4326', dst_transform=vt, dst_crs='EPSG:4326', resampling=Resampling.nearest)
    r['mask_stretched_vs_geo_mismatch_in_poly'] = float((st != (geo > 0))[inpoly].mean())
    res.append(r)
for r in res: print(json.dumps(r, ensure_ascii=False))
