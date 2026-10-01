NAMES=['N-35-11-В-а-2','O-35-142-В-г-3','O-35-142-В-б-3']
from PIL import Image
def canvas_check(name, poly):
    d = '/data_output/tiles/' + name
    with rasterio.open(FILES[name]) as s:
        X0, Y0, _, _ = tile_origin(s); h, w = s.height, s.width
        data = s.read(1)
        m = geometry_mask([shapely.geometry.mapping(poly)], out_shape=(h, w), transform=s.transform, invert=True)
    files = {tuple(map(int, os.path.splitext(f)[0].split('_')[1:])): f for f in os.listdir(d) if f.startswith('17_')}
    tx0, ty0 = X0//256, Y0//256
    cols, rows = w//256, h//256
    n_exp = cols*rows; present = 0; black = 0; tiles_outside_only = 0
    img_black_in = img_black_out = 0; n_in = n_out = 0
    miss_mask = np.zeros((h, w), bool)
    for ty in range(rows):
        for tx in range(cols):
            f = files.get((tx0+tx, ty0+ty))
            sl = (slice(ty*256, ty*256+256), slice(tx*256, tx*256+256))
            if f is None:
                miss_mask[sl] = True; continue
            present += 1
            a = np.asarray(Image.open(os.path.join(d, f)).convert('RGB'))
            b = (a.sum(axis=2) == 0)
            mi = m[sl]
            img_black_in += int(b[mi].sum()); n_in += int(mi.sum())
            img_black_out += int(b[~mi].sum()); n_out += int((~mi).sum())
    r = dict(name=name, tiles_expected=n_exp, tiles_present=present, tile_origin_ok=(tx0 == min(k[0] for k in files)) and (ty0 == min(k[1] for k in files)),
             px_in=n_in, px_out=n_out, black_share_in=img_black_in/max(n_in, 1), black_share_out=img_black_out/max(n_out, 1),
             out_vals={int(v): int(c) for v, c in zip(*np.unique(data[~m], return_counts=True))})
    if miss_mask.any():
        r['missing_px'] = int(miss_mask.sum()); r['missing_px_inside_poly'] = int((miss_mask & m).sum())
        r['missing_vals'] = {int(v): int(c) for v, c in zip(*np.unique(data[miss_mask], return_counts=True))}
    return r
if __name__ == '__main__':
    SH = sheets(); FILES = raster_files()
    for n in json.loads(sys.argv[1] if len(sys.argv) > 1 else '[]') or NAMES:
        print(json.dumps(canvas_check(n, SH[n]), ensure_ascii=False), flush=True)
