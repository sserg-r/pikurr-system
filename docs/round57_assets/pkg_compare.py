#!/usr/bin/env python3
"""Сравнение нового пакета (N) с пакетом A на проде: stats, сценарии, площади, эталоны, доля класса 5.
Использование: python3 pkg_compare.py <каталог A> <каталог N>  (в каждом — vectors.gpkg, manifest.json)
Правило valuation и площадь — как в create_assessment_schema.sql (площадь участка: v3 — первая часть, v4 — объединение частей)."""
import sys, json, sqlite3, collections, hashlib
import numpy as np
sys.path.insert(0, '.')
from calc import area_ha, gpb
from shapely import from_wkb
import shapely
A_DIR, N_DIR = sys.argv[1], sys.argv[2]

def load(d):
    c = sqlite3.connect(f'file:{d}/vectors.gpkg?mode=ro', uri=True)
    st = {r[0]: json.loads(r[1]) for r in c.execute('select fid_ext, stats from assessment')}
    P = collections.defaultdict(list)
    for fid, nr, bc, nd, g in c.execute('select ogc_fid, nr_user, ball_co, ndohod_d, geom from agrifields order by ogc_fid'):
        P[nr].append((bc, nd, from_wkb(gpb(g))))
    return st, P
def val(bc, nd, s):
    v = [float(s.get(str(i), 0)) for i in range(6)]; t = sum(v); fr = (v[0] + v[1] + v[2]) / t if t else 0
    if fr > 0.4 and nd <= 0: return 'forest'
    if fr > 0.3 and nd > 0: return 'clearing'
    if bc > 24: return 'tillage'
    return 'meadow'
def mx(a, b): return max(abs(a.get(str(i), 0) - b.get(str(i), 0)) for i in range(6))
SA, PA = load(A_DIR); SN, PN = load(N_DIR)
def keyinfo(P, union):
    out = {}
    for nr, v in P.items():
        g = shapely.union_all([x[2] for x in v]) if (union and len(v) > 1) else v[0][2]
        out[nr] = (v[0][0], v[0][1], round(area_ha(g), 2))
    return out
IA = keyinfo(PA, union=False)          # прод (схема v3): первая часть
IN = keyinfo(PN, union=True)           # новая схема v4: объединение частей
print('ключей stats: A', len(SA), 'N', len(SN), '; общих', len(set(SA) & set(SN)))
common = sorted(set(SA) & set(SN))
d = np.array([mx(SA[k], SN[k]) for k in common])
print('stats: изменились (>1e-9) у %d из %d (%.1f%%); max|Δ|: медиана по изменившимся %.4f, p90 %.4f, p99 %.4f, max %.3f; >0.1: %d; >0.3: %d' % (
    (d > 1e-9).sum(), len(d), 100 * (d > 1e-9).mean(), np.median(d[d > 1e-9]), np.quantile(d[d > 1e-9], .9), np.quantile(d[d > 1e-9], .99), d.max(), (d > .1).sum(), (d > .3).sum()))
tr = collections.Counter(); n_ch = 0
for k in common:
    nr = str(k); ba, na_, _ = IA[nr]; bn, nn, _ = IN[nr]
    va, vn = val(ba, na_, SA[k]), val(bn, nn, SN[k])
    if va != vn: tr[(va, vn)] += 1; n_ch += 1
print('сценарий изменился у %d участков; переходы: %s' % (n_ch, dict(tr)))
def dist_stats(S, I, prefix):
    by = collections.defaultdict(lambda: [0, 0.0, 0.0, collections.Counter(), collections.Counter()])
    for k, s in S.items():
        nr = str(k); bc, nd, a = I[nr]; d4 = nr[:4]; sc = val(bc, nd, s)
        r = by[d4]; r[0] += 1; r[1] += a; r[2] += a * s.get('5', 0); r[3][sc] += 1; r[4][sc] += a
    return by
BA = dist_stats(SA, IA, 'A'); BN = dist_stats(SN, IN, 'N')
print('\nрайон | участков A/N | площадь га A/N | доля класса 5 (по площади) A/N')
for d4 in sorted(BA):
    a, n = BA[d4], BN[d4]
    print(f'{d4} | {a[0]}/{n[0]} | {a[1]:.1f}/{n[1]:.1f} | {100*a[2]/a[1]:.2f}%/{100*n[2]/n[1]:.2f}%')
ta = sum(r[2] for r in BA.values()) / sum(r[1] for r in BA.values()); tn = sum(r[2] for r in BN.values()) / sum(r[1] for r in BN.values())
print('всего доля класса 5: A %.2f%%, N %.2f%%' % (100 * ta, 100 * tn))
print('\nЭТАЛОНЫ')
for lab, S, I in (('A', SA, IA), ('N', SN, IN)):
    sel = [k for k in S if str(k).startswith('2212')]
    cnt = collections.Counter(); ar = collections.Counter()
    for k in sel:
        bc, nd, a = I[str(k)]; sc = val(bc, nd, S[k]); cnt[sc] += 1; ar[sc] += a
    tot = sum(I[str(k)][2] for k in sel)
    print(lab, 'район 2212:', len(sel), 'объектов,', round(tot, 1), 'га;', {s: (cnt[s], round(ar[s], 1)) for s in sorted(cnt)})
    p = [k for k in S if str(k).startswith('2212000055')]
    print(lab, '2212000055:', len(p), 'объект(ов),', round(sum(I[str(k)][2] for k in p), 1), 'га;', [val(I[str(k)][0], I[str(k)][1], S[k]) for k in p])
