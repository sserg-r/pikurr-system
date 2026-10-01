from skimage.morphology import closing, disk
from skimage.transform import resize
from rasterio.features import sieve
from rasterio.warp import reproject, Resampling
NAMES = ['N-35-11-В-а-2', 'O-35-142-В-г-3', 'N-36-13-Б-б-2', 'N-35-10-А-а-2']
def combined(name):
    arrs = []
    for y in (2023, 2024, 2025):
        p = f'{USAB}/{y}/{name}.tif'
        if os.path.exists(p):
            with rasterio.open(p) as s: arrs.append((s.read(1), s.transform, s.crs, s.bounds))
    shp = arrs[0][0].shape
    a = []
    for d, _, _, _ in arrs:
        if d.shape != shp: d = resize(d, shp, order=0, preserve_range=True, anti_aliasing=False)
        a.append(d)
    c = np.array(a).any(axis=0)
    c = closing(c, disk(1)); c = sieve(c.astype(np.uint8), 10, connectivity=4)
    return c, arrs[0][1], arrs[0][3]
def run(name, SH):
    with rasterio.open(f'{VEGET}/{name}.tif') as s: veg = s.read(1); vt = s.transform; vb = s.bounds
    with rasterio.open(f'{FINAL}/{name}.tif') as s: fin = s.read(1)
    c, ut, ub = combined(name)
    stretched = resize(c, veg.shape, preserve_range=True) > 0           # как в classify.py
    geo = np.zeros(veg.shape, np.uint8)
    reproject(c.astype(np.uint8), geo, src_transform=ut, src_crs='EPSG:4326', dst_transform=vt, dst_crs='EPSG:4326', resampling=Resampling.nearest)
    geo = geo > 0                                                         # та же маска, посаженная по геопривязке
    f_repro = veg.copy(); f_repro[stretched & (veg == 3)] = 5
    poly = SH[name]; pb = poly.bounds
    h, w = veg.shape
    inpoly = geometry_mask([shapely.geometry.mapping(poly)], out_shape=(h, w), transform=vt, invert=True)
    out = dict(name=name, usab_shape=list(c.shape), usab_bounds=[ub.left, ub.bottom, ub.right, ub.top], poly_bbox=list(pb), canvas_bounds=[vb.left, vb.bottom, vb.right, vb.top],
               px_deg_lon_usab=(ub.right-ub.left)/c.shape[1], px_deg_lon_canvas=(vb.right-vb.left)/w,
               final_reproduced=bool((f_repro == fin).all()), final_mismatch_px=int((f_repro != fin).sum()))
    # смещение при растяжении: левый край/правый край/центр, в пикселях холста
    cx = lambda lon: (lon - vb.left)/(vb.right-vb.left)*w
    cy = lambda lat: (vb.top - lat)/(vb.top-vb.bottom)*h
    out['true_pos_of_usab_edges_px'] = dict(left=cx(ub.left), right=cx(ub.right), top=cy(ub.top), bottom=cy(ub.bottom), canvas_w=w, canvas_h=h)
    mis = stretched != geo
    out['mask_stretched_vs_geo'] = dict(mismatch_share_all=float(mis.mean()), mismatch_share_inpoly=float(mis[inpoly].mean()),
                                        mask_true_share=float(geo.mean()), mask_stretched_share=float(stretched.mean()))
    # зависимость от удалённости от центра холста (по x), 8 интервалов
    xs = np.arange(w)[None, :].repeat(h, 0); d = np.abs(xs - w/2)/(w/2)
    bins = np.digitize(d, [0.25, 0.5, 0.75, 0.9, 1.01])
    out['mismatch_by_dist_from_center_x'] = {f'{lo}-{hi}': float(mis[(bins == i)].mean()) for i, (lo, hi) in enumerate([(0, .25), (.25, .5), (.5, .75), (.75, .9), (.9, 1.0)])}
    return out
if __name__ == '__main__':
    SH = sheets()
    for n in NAMES: print(json.dumps(run(n, SH), ensure_ascii=False), flush=True)
