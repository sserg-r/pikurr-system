from multiprocessing import Pool
import hashlib
from PIL import Image
INFO = None
def work(pair):
    a, b = pair
    ia, ib = INFO[a], INFO[b]
    tx0 = max(ia['X0'], ib['X0'])//256; ty0 = max(ia['Y0'], ib['Y0'])//256
    tx1 = min(ia['X0']+ia['w'], ib['X0']+ib['w'])//256; ty1 = min(ia['Y0']+ia['h'], ib['Y0']+ib['h'])//256
    n = same = diff = missing = 0; mad = []
    for ty in range(ty0, ty1):
        for tx in range(tx0, tx1):
            pa = f'/data_output/tiles/{a}/17_{tx}_{ty}.jpg'; pb = f'/data_output/tiles/{b}/17_{tx}_{ty}.jpg'
            n += 1
            if not (os.path.exists(pa) and os.path.exists(pb)): missing += 1; continue
            if open(pa, 'rb').read() == open(pb, 'rb').read(): same += 1
            else:
                diff += 1
                x = np.asarray(Image.open(pa).convert('RGB')).astype(int); y = np.asarray(Image.open(pb).convert('RGB')).astype(int)
                mad.append(float(np.abs(x - y).mean()))
    return dict(a=a, b=b, n=n, same=same, diff=diff, missing=missing, mad=mad)
if __name__ == '__main__':
    FILES = raster_files(); INFO = {}
    for n, p in FILES.items():
        with rasterio.open(p) as s:
            X0, Y0, _, _ = tile_origin(s); INFO[n] = dict(X0=X0, Y0=Y0, w=s.width, h=s.height)
    names = sorted(INFO)
    from shapely import STRtree
    boxes = [shapely.geometry.box(INFO[n]['X0'], INFO[n]['Y0'], INFO[n]['X0']+INFO[n]['w'], INFO[n]['Y0']+INFO[n]['h']) for n in names]
    tr = STRtree(boxes)
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in tr.query(boxes[i], predicate='intersects') if j > i and boxes[i].intersection(boxes[j]).area > 0]
    with Pool(3) as pool:
        for r in pool.imap_unordered(work, pairs, chunksize=8): print(json.dumps(r), flush=True)
