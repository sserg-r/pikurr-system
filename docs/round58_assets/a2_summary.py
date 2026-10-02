# Сводка блока A раунда 58: python3 a2_summary.py a1.jsonl
import sys, json
import numpy as np
rows = []; extra = None
for l in open(sys.argv[1], encoding='utf-8'):
    d = json.loads(l)
    if 'summary' in d: extra = d; continue
    rows.append(d)
VER = ('old', 'new', 'ctrl')
n3 = {v: np.array([r[f'{v}3'] for r in rows]) for v in VER}
n5 = {v: np.array([r[f'{v}5'] for r in rows]) for v in VER}
dist = np.array([r['d'] if r['d'] is not None else np.nan for r in rows])
tot = {v: n3[v] + n5[v] for v in VER}
print('участков всего (nr_user):', len(rows), '; сумма n3+n5 (old/new/ctrl) совпадает:', all(np.array_equal(tot['old'], tot[v]) for v in VER))
sel0 = tot['new'] >= 50
print('участков с n3+n5 >= 50:', int(sel0.sum()))
def stats(sel, label):
    print(f'\n== {label}: участков {int(sel.sum())}')
    out = {}
    for v in VER:
        p = n5[v][sel] / tot[v][sel]
        hom = float(((p <= .1) | (p >= .9)).mean()); mix = float(((p >= .3) & (p <= .7)).mean())
        imp = float(np.minimum(p, 1 - p).mean())
        h = np.histogram(p, bins=10, range=(0, 1))[0]
        out[v] = p
        print(f'  {v:5s}: однородные {hom*100:6.2f} %  смешанные {mix*100:6.2f} %  средняя неоднородность min(p,1-p) {imp:.4f}')
        print('         гистограмма p (10 интервалов, доли %):', ' '.join(f'{x/ len(p)*100:5.1f}' for x in h))
    # парное сравнение по участку: неоднородность min(p,1-p)
    io, inw, ic = [np.minimum(out[v], 1 - out[v]) for v in VER]
    print(f'  парно old→new: неоднородность меньше у {(inw < io).sum()}, больше у {(inw > io).sum()}, равна у {(inw == io).sum()}')
    print(f'  парно new→ctrl: неоднородность меньше у {(ic < inw).sum()}, больше у {(ic > inw).sum()}, равна у {(ic == inw).sum()}')
stats(sel0, 'все участки')
for lo, hi, lab in ((0, 150, 'до 150 м от края полигона листа'), (150, 500, '150–500 м'), (500, 1e9, 'глубже 500 м')):
    stats(sel0 & (dist >= lo) & (dist < hi), lab)
if extra: print('\nКонтроль воспроизведения нового итога пересчётом (доля совпавших пикселей):', extra)
