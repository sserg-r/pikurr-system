from multiprocessing import Pool
SH = None
def work(name):
    poly = SH[name]
    p = FILES[name]
    with rasterio.open(p) as s:
        h, w = s.height, s.width
        data = s.read(1)
        X0, Y0, fx, fy = tile_origin(s)
        b = s.bounds
        bb = box(b.left, b.bottom, b.right, b.top)
        a_r = area_ha(bb); a_in = area_ha(bb.intersection(poly))
        m = geometry_mask([shapely.geometry.mapping(poly)], out_shape=(h, w), transform=s.transform, invert=True)  # True = внутри
        out = {}
        for k, mm in (('in', m), ('out', ~m)):
            vals, cnt = np.unique(data[mm], return_counts=True)
            out[k] = {int(v): int(c) for v, c in zip(vals, cnt)}
        return dict(name=name, w=w, h=h, X0=X0, Y0=Y0, frac_off=(fx-X0, fy-Y0), bounds=[b.left, b.bottom, b.right, b.top],
                    area_raster_ha=a_r, area_inpoly_ha=a_in, area_poly_ha=area_ha(poly), hist=out)
if __name__ == '__main__':
    SH = sheets(); FILES = raster_files()
    with Pool(14) as pool:
        for r in pool.imap_unordered(work, sorted(FILES)):
            print(json.dumps(r, ensure_ascii=False), flush=True)
