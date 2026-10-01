from multiprocessing import Pool
import random
from rasterio.windows import Window
from rasterio.windows import transform as wtransform
exec(open('/dev/null').read())
INFO = None; SH = None
def canv(name):
    with rasterio.open(f'{VEGET}/{name}.tif') as s: veg = s.read(1); vt = s.transform
    c, ut, ub = combined(name)
    st = resize(c, veg.shape, preserve_range=True) > 0
    geo = np.zeros(veg.shape, np.uint8)
    reproject(c.astype(np.uint8), geo, src_transform=ut, src_crs='EPSG:4326', dst_transform=vt, dst_crs='EPSG:4326', resampling=Resampling.nearest)
    geo = geo > 0
    f_st = veg.copy(); f_st[st & (veg == 3)] = 5
    f_geo = veg.copy(); f_geo[geo & (veg == 3)] = 5
    return veg, f_st, f_geo, vt
def work(pair):
    a, b = pair
    ia, ib = INFO[a], INFO[b]
    gx0 = max(ia['X0'], ib['X0']); gy0 = max(ia['Y0'], ib['Y0'])
    gx1 = min(ia['X0']+ia['w'], ib['X0']+ib['w']); gy1 = min(ia['Y0']+ia['h'], ib['Y0']+ib['h'])
    w, h = gx1-gx0, gy1-gy0
    va, sa, ga, ta = canv(a); vb, sb, gb, tb = canv(b)
    sl = lambda arr, i: arr[gy0-i['Y0']:gy0-i['Y0']+h, gx0-i['X0']:gx0-i['X0']+w]
    wa = wtransform(Window(gx0-ia['X0'], gy0-ia['Y0'], w, h), ta); wb = wtransform(Window(gx0-ib['X0'], gy0-ib['Y0'], w, h), tb)
    ma = geometry_mask([shapely.geometry.mapping(SH[a])], out_shape=(h, w), transform=wa, invert=True)
    mb = geometry_mask([shapely.geometry.mapping(SH[b])], out_shape=(h, w), transform=wb, invert=True)
    sel = ma ^ mb
    n = int(sel.sum())
    r = dict(a=a, b=b, n=n,
             dis_veg=int((sl(va, ia)[sel] != sl(vb, ib)[sel]).sum()),
             dis_final_stretched=int((sl(sa, ia)[sel] != sl(sb, ib)[sel]).sum()),
             dis_final_geo=int((sl(ga, ia)[sel] != sl(gb, ib)[sel]).sum()))
    return r
if __name__ == '__main__':
    SH = sheets(); FILES = raster_files(); INFO = {}
    for n, p in FILES.items():
        with rasterio.open(p) as s:
            X0, Y0, _, _ = tile_origin(s); INFO[n] = dict(X0=X0, Y0=Y0, w=s.width, h=s.height)
    names = sorted(INFO)
    from shapely import STRtree
    boxes = [shapely.geometry.box(INFO[n]['X0'], INFO[n]['Y0'], INFO[n]['X0']+INFO[n]['w'], INFO[n]['Y0']+INFO[n]['h']) for n in names]
    tr = STRtree(boxes)
    pairs = []
    for i in range(len(names)):
        for j in tr.query(boxes[i], predicate='intersects'):
            if j > i:
                x0, y0, x1, y1 = boxes[i].intersection(boxes[j]).bounds
                if (x1-x0)*(y1-y0) > 256*256+1: pairs.append((names[i], names[j]))
    random.seed(7); pairs = random.sample(pairs, 60)
    with Pool(8) as pool:
        for r in pool.imap_unordered(work, pairs): print(json.dumps(r, ensure_ascii=False), flush=True)
