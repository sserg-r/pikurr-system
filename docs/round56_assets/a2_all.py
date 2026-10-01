from multiprocessing import Pool
import filecmp
exec(open('/dev/null').read())
SHP = None
def mask_one(name):
    with rasterio.open(f'{VEGET}/{name}.tif') as s: veg = s.read(1); vt = s.transform; vb = s.bounds
    c, ut, ub = combined(name)
    h, w = veg.shape
    stretched = resize(c, veg.shape, preserve_range=True) > 0
    geo = np.zeros(veg.shape, np.uint8)
    reproject(c.astype(np.uint8), geo, src_transform=ut, src_crs='EPSG:4326', dst_transform=vt, dst_crs='EPSG:4326', resampling=Resampling.nearest)
    geo = geo > 0
    inpoly = geometry_mask([shapely.geometry.mapping(SHP[name])], out_shape=(h, w), transform=vt, invert=True)
    mis = stretched != geo
    cell = abs(vt.a)
    ox = lambda lon: (lon - vb.left)/cell
    oy = lambda lat: (vb.top - lat)/abs(vt.e)
    return dict(name=name, off_left=ox(ub.left), off_right=w - ox(ub.right), off_top=oy(ub.top), off_bottom=h - oy(ub.bottom),
                mis_in=float(mis[inpoly].mean()), mis_all=float(mis.mean()),
                maskshare_geo_in=float(geo[inpoly].mean()), maskshare_str_in=float(stretched[inpoly].mean()),
                mis_geo_not_str=float((geo & ~stretched)[inpoly].mean()), mis_str_not_geo=float((stretched & ~geo)[inpoly].mean()),
                m_per_px=cell*111320*math.cos(math.radians(vb.top)))
if __name__ == '__main__':
    SHP = sheets(); FILES = raster_files()
    with Pool(14) as pool:
        for r in pool.imap_unordered(mask_one, sorted(FILES), chunksize=2): print(json.dumps(r, ensure_ascii=False), flush=True)
