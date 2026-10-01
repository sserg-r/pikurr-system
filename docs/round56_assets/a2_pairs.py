from multiprocessing import Pool
from rasterio.windows import Window
from rasterio.windows import transform as wtransform
BINS = [0, 15, 30, 60, 100, 150, 200, 256, 10**9]   # расстояние до края холста "чужого" листа, пикс
NB = len(BINS) - 1
INFO = None; SH = None
def read_win(path, x0, y0, X0, Y0, w, h):
    # окно [x0,x0+w) x [y0,y0+h) в глобальных пикселях -> окно растра с началом (X0,Y0)
    with rasterio.open(path) as s:
        return s.read(1, window=Window(x0 - X0, y0 - Y0, w, h)), s.transform
def work(pair):
    a, b = pair
    ia, ib = INFO[a], INFO[b]
    gx0 = max(ia['X0'], ib['X0']); gy0 = max(ia['Y0'], ib['Y0'])
    gx1 = min(ia['X0'] + ia['w'], ib['X0'] + ib['w']); gy1 = min(ia['Y0'] + ia['h'], ib['Y0'] + ib['h'])
    w, h = gx1 - gx0, gy1 - gy0
    if w <= 0 or h <= 0: return None
    fa, ta = read_win(FILES[a], gx0, gy0, ia['X0'], ia['Y0'], w, h)
    fb, tb = read_win(FILES[b], gx0, gy0, ib['X0'], ib['Y0'], w, h)
    va, _ = read_win(f'{VEGET}/{a}.tif', gx0, gy0, ia['X0'], ia['Y0'], w, h)
    vb, _ = read_win(f'{VEGET}/{b}.tif', gx0, gy0, ib['X0'], ib['Y0'], w, h)
    # окна трансформов для принадлежности полигону (по собственной геопривязке каждого растра)
    wa = wtransform(Window(gx0 - ia['X0'], gy0 - ia['Y0'], w, h), ta)
    wb = wtransform(Window(gx0 - ib['X0'], gy0 - ib['Y0'], w, h), tb)
    ma = geometry_mask([shapely.geometry.mapping(SH[a])], out_shape=(h, w), transform=wa, invert=True)
    mb = geometry_mask([shapely.geometry.mapping(SH[b])], out_shape=(h, w), transform=wb, invert=True)
    yy, xx = np.mgrid[gy0:gy1, gx0:gx1]
    def dist(i):  # расстояние до края холста листа i
        return np.minimum.reduce([xx - i['X0'], i['X0'] + i['w'] - 1 - xx, yy - i['Y0'], i['Y0'] + i['h'] - 1 - yy])
    out = dict(a=a, b=b, w=int(w), h=int(h), n=int(w*h), only_a=int((ma & ~mb).sum()), only_b=int((mb & ~ma).sum()),
               both=int((ma & mb).sum()), neither=int((~ma & ~mb).sum()))
    res = {}
    for key, own_is_a, sel in (('own_a', True, ma & ~mb), ('own_b', False, mb & ~ma)):
        if not sel.any(): continue
        fo, ff = (fa, fb) if own_is_a else (fb, fa)          # финальные: свой / чужой
        vo, vf = (va, vb) if own_is_a else (vb, va)
        d = dist(ib if own_is_a else ia)                     # расстояние до края холста ЧУЖОГО листа
        M = np.zeros((6, 6), np.int64)
        np.add.at(M, (fo[sel].astype(int), ff[sel].astype(int)), 1)
        Mv = np.zeros((6, 6), np.int64)
        np.add.at(Mv, (vo[sel].astype(int), vf[sel].astype(int)), 1)
        ds = d[sel]; bi = np.digitize(ds, BINS[1:-1])
        dis = fo[sel] != ff[sel]; disv = vo[sel] != vf[sel]
        inv5 = (fo[sel] == 5) | (ff[sel] == 5)
        mask_only = dis & (vo[sel] == vf[sel])               # веге совпала, финал различается: маска обработки
        seg = dis & (vo[sel] != vf[sel])
        bins = []
        for k in range(NB):
            m = bi == k
            bins.append([int(m.sum()), int((dis & m).sum()), int((disv & m).sum()), int((mask_only & m).sum()), int((seg & m).sum()),
                         int((dis & inv5 & m).sum()), int((mask_only & inv5 & m).sum())])
        res[key] = dict(M=M.tolist(), Mv=Mv.tolist(), bins=bins)
    out['res'] = res
    return out
if __name__ == '__main__':
    SH = sheets(); FILES = raster_files()
    INFO = {}
    for n, p in FILES.items():
        with rasterio.open(p) as s:
            X0, Y0, _, _ = tile_origin(s); INFO[n] = dict(X0=X0, Y0=Y0, w=s.width, h=s.height)
    names = sorted(INFO)
    from shapely import STRtree
    boxes = [shapely.geometry.box(INFO[n]['X0'], INFO[n]['Y0'], INFO[n]['X0'] + INFO[n]['w'], INFO[n]['Y0'] + INFO[n]['h']) for n in names]
    tr = STRtree(boxes)
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in tr.query(boxes[i], predicate='intersects') if j > i and boxes[i].intersection(boxes[j]).area > 0]
    print('PAIRS', len(pairs), file=sys.stderr, flush=True)
    with Pool(14) as pool:
        for r in pool.imap_unordered(work, pairs, chunksize=4):
            if r: print(json.dumps(r, ensure_ascii=False), flush=True)
