SH = sheets(); FILES = raster_files(); out = []
for n in sorted(FILES):
    with rasterio.open(f'{USAB}/2025/{n}.tif') as s: ub = s.bounds; shp = (s.height, s.width)
    pb = SH[n].bounds
    out.append([abs(ub.left-pb[0]), abs(ub.bottom-pb[1]), abs(ub.right-pb[2]), abs(ub.top-pb[3])])
a = np.array(out); m = 111320*math.cos(math.radians(55.5))
print(json.dumps(dict(n=len(a), max_deg=float(a.max()), max_m_lon=float(a[:, [0, 2]].max()*m), max_m_lat=float(a[:, [1, 3]].max()*111320), median_m_lon=float(np.median(a[:, [0, 2]])*m), p99_m=float(np.quantile(a[:, [0, 2]], .99)*m))))
