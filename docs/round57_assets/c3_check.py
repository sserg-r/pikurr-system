from src.tasks.export import ExportTask
from scipy.ndimage import binary_erosion
from rasterio.windows import Window
NAMES = ['N-35-34-В-а-4','N-35-34-В-а-3','N-35-34-В-а-2','N-35-34-В-а-1','N-35-34-В-б-3','N-35-34-В-б-1','N-35-34-А-в-4','N-35-34-А-в-3']
tt = ExportTask().trans_tab; SH = sheets()
def load(tag, n):
    with rasterio.open(f'/cmp_{tag}/2025/{n.translate(tt)}.tif') as s: return s.read(1), s
D = {}; info = {}
for n in NAMES:
    for tag in ('old', 'new'):
        D[(tag, n)], s = load(tag, n)
    info[n] = dict(X0=tile_origin(s)[0], Y0=tile_origin(s)[1], w=s.width, h=s.height, t=s.transform)
print('листов', len(NAMES))
# 1. общие непустые пиксели у соседей (глобальная сетка)
for tag in ('old', 'new'):
    tot = 0; pairs = 0; npairs = 0
    for i, a in enumerate(NAMES):
        for b in NAMES[i+1:]:
            ia, ib = info[a], info[b]
            x0 = max(ia['X0'], ib['X0']); y0 = max(ia['Y0'], ib['Y0']); x1 = min(ia['X0']+ia['w'], ib['X0']+ib['w']); y1 = min(ia['Y0']+ia['h'], ib['Y0']+ib['h'])
            if x1 <= x0 or y1 <= y0: continue
            npairs += 1
            pa = D[(tag, a)][y0-ia['Y0']:y1-ia['Y0'], x0-ia['X0']:x1-ia['X0']]; pb = D[(tag, b)][y0-ib['Y0']:y1-ib['Y0'], x0-ib['X0']:x1-ib['X0']]
            c = int(((pa > 0) & (pb > 0)).sum()); tot += c; pairs += c > 0
    print(f'{tag}: пар с перекрытием растров {npairs}; общих непустых пикселей {tot}; пар с общими непустыми {pairs}')
# 2. новое = старое ∩ полигон; покрытие внутри полигонов
sys.path.insert(0, '/app')
from src.tasks.export import sheet_polygon_mask
bad_sub = 0; lost = 0; outside = 0; tot_old = 0
for n in NAMES:
    o, nw, i = D[('old', n)], D[('new', n)], info[n]
    inp = sheet_polygon_mask(SH[n], i['t'], o.shape)
    inner = binary_erosion(inp, iterations=2)
    bad_sub += int(((nw > 0) & ~(o > 0)).sum())                 # новое не вне старого
    lost += int(((o > 0) & inner & ~(nw > 0)).sum())            # потеряно внутри полигона (без полосы 2 пикс у границы)
    outside += int(((nw > 0) & ~inp).sum())                      # непустых вне полигона
    tot_old += int((o > 0).sum())
    same_inside = bool(((o > 0) & inp == (nw > 0)).all()) and bool(((o == nw) | ~inp).all())
    print(n, 'значения внутри полигона совпадают со старыми:', bool((o[inp] == nw[inp]).all()), '| непустых old/new:', int((o > 0).sum()), int((nw > 0).sum()))
print('непустых new вне старых:', bad_sub, '; потеряно внутри полигона (без 2 пикс у границы):', lost, '; непустых new вне полигона:', outside, '; всего непустых old:', tot_old)
