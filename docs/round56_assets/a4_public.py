from multiprocessing import Pool
from rasterio.windows import Window
from rasterio.windows import transform as wtransform
from src.tasks.export import ExportTask
INFO = None; SH = None; PUB = None
def rd(path, x0, y0, X0, Y0, w, h):
    with rasterio.open(path) as s:
        return s.read(1, window=Window(x0 - X0, y0 - Y0, w, h)), s.transform
def work(pair):
    a, b = pair
    ia, ib = INFO[a], INFO[b]
    gx0 = max(ia['X0'], ib['X0']); gy0 = max(ia['Y0'], ib['Y0'])
    gx1 = min(ia['X0']+ia['w'], ib['X0']+ib['w']); gy1 = min(ia['Y0']+ia['h'], ib['Y0']+ib['h'])
    w, h = gx1-gx0, gy1-gy0
    pa, ta = rd(PUB[a], gx0, gy0, ia['X0'], ia['Y0'], w, h)
    pb, tb = rd(PUB[b], gx0, gy0, ib['X0'], ib['Y0'], w, h)
    both = (pa > 0) & (pb > 0)
    out = dict(a=a, b=b, n=int(w*h), nz_a=int((pa > 0).sum()), nz_b=int((pb > 0).sum()), both=int(both.sum()),
               diff=int((both & (pa != pb)).sum()), samples=[])
    if out['diff'] > 0:
        d = both & (pa != pb)
        # кандидаты: окрестность 9x9 однородна в обоих растрах (устойчиво к ресэмплингу в мозаике)
        from scipy.ndimage import minimum_filter, maximum_filter
        ua = (minimum_filter(pa, size=9) == maximum_filter(pa, size=9)); ub = (minimum_filter(pb, size=9) == maximum_filter(pb, size=9))
        cand = np.argwhere(d & ua & ub)
        if len(cand):
            r, c = cand[len(cand)//2]
            wa = wtransform(Window(gx0-ia['X0'], gy0-ia['Y0'], w, h), ta)
            lon, lat = wa * (c + 0.5, r + 0.5)
            from shapely.geometry import Point
            pt = Point(lon, lat)
            out['samples'].append(dict(lon=lon, lat=lat, val_a=int(pa[r, c]), val_b=int(pb[r, c]), a_poly=bool(SH[a].contains(pt)), b_poly=bool(SH[b].contains(pt)),
                                       gx=int(gx0+c), gy=int(gy0+r)))
    return out
if __name__ == '__main__':
    SH = sheets(); FILES = raster_files()
    tt = ExportTask().trans_tab
    PUB = {n: f'{PUBLIC}/{n.translate(tt)}.tif' for n in FILES}
    missing = [n for n, p in PUB.items() if not os.path.exists(p)]
    print('PUBLIC_MISSING', len(missing), file=sys.stderr)
    INFO = {}
    for n, p in PUB.items():
        if n in missing: continue
        with rasterio.open(p) as s:
            X0, Y0, _, _ = tile_origin(s); INFO[n] = dict(X0=X0, Y0=Y0, w=s.width, h=s.height)
    names = sorted(INFO)
    from shapely import STRtree
    boxes = [shapely.geometry.box(INFO[n]['X0'], INFO[n]['Y0'], INFO[n]['X0']+INFO[n]['w'], INFO[n]['Y0']+INFO[n]['h']) for n in names]
    tr = STRtree(boxes)
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in tr.query(boxes[i], predicate='intersects') if j > i and boxes[i].intersection(boxes[j]).area > 0]
    print('PAIRS', len(pairs), file=sys.stderr, flush=True)
    with Pool(14) as pool:
        for r in pool.imap_unordered(work, pairs, chunksize=4): print(json.dumps(r, ensure_ascii=False), flush=True)
