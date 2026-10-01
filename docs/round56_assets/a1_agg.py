import json, numpy as np, itertools, collections
import sys; sys.path.insert(0,'..')
from shapely.geometry import box
from shapely import STRtree
import shapely
from shapely.ops import unary_union
from calc import area_ha
R=[json.loads(l) for l in open('a1.jsonl')]
print("листов",len(R), "размеры растров:",collections.Counter((r['w'],r['h']) for r in R).most_common(5))
fo=np.array([1-r['area_inpoly_ha']/r['area_raster_ha'] for r in R])
def q(x): return {k:round(float(v)*100,2) for k,v in zip(("min","p10","p25","медиана","p75","p90","p99","max"),np.quantile(x,[0,.1,.25,.5,.75,.9,.99,1]))}
print("доля площади растра вне полигона (геометрия), %:",q(fo))
tot_in=sum(sum(r['hist']['in'].values()) for r in R); tot_out=sum(sum(r['hist']['out'].values()) for r in R)
fp=np.array([sum(r['hist']['out'].values())/(sum(r['hist']['out'].values())+sum(r['hist']['in'].values())) for r in R])
print("то же по пикселям, %:",q(fp)," всего пикселей вне полигона: %.2f%%"%(100*tot_out/(tot_in+tot_out)))
print("площадь растров, га:",round(sum(r['area_raster_ha'] for r in R)),"площадь полигонов 912 листов:",round(sum(r['area_poly_ha'] for r in R)),"внутри полигона:",round(sum(r['area_inpoly_ha'] for r in R)))
# значения вне полигона
ho=collections.Counter(); hi=collections.Counter()
for r in R:
    for k,v in r['hist']['out'].items(): ho[int(k)]+=v
    for k,v in r['hist']['in'].items(): hi[int(k)]+=v
print("классы внутри полигона, %:",{k:round(100*v/tot_in,2) for k,v in sorted(hi.items())})
print("классы вне полигона, %:",{k:round(100*v/tot_out,2) for k,v in sorted(ho.items())})
print("пикселей со значением 255 всего:",ho.get(255,0)+hi.get(255,0))
print("max/min значения:",max(list(ho)+list(hi)),min(list(ho)+list(hi)))
# перекрытие прямоугольников растров (в пикселях глобальной сетки)
rects=[(r['X0'],r['Y0'],r['X0']+r['w'],r['Y0']+r['h'],r['name']) for r in R]
boxes=[box(*r[:4]) for r in rects]
tree=STRtree(boxes)
pairs=[]
for i,b in enumerate(boxes):
    for j in tree.query(b,predicate='intersects'):
        if j>i:
            inter=b.intersection(boxes[j])
            if inter.area>0: pairs.append((i,j,inter))
print("пар соседей с перекрытием растров:",len(pairs))
# площадь (пиксели -> га): считаем через lon/lat границы
geo=[box(*r['bounds']) for r in R]
ov=[geo[i].intersection(geo[j]) for i,j,_ in pairs]
ov=[o for o in ov if o.area>0]
U=unary_union(ov)
print("площадь зон перекрытия (>=2 растров, объединение), га:",round(area_ha(U),1),"; сумма попарных:",round(sum(area_ha(o) for o in ov),1))
# кратность
areas_pairs=[area_ha(o) for o in ov]
print("перекрытие пары: медиана га",round(float(np.median(areas_pairs)),1),"max",round(max(areas_pairs),1))
# размеры полосы в пикселях
wid=[]; 
for i,j,inter in pairs:
    x0,y0,x1,y1=inter.bounds; wid.append((x1-x0,y1-y0))
print("размеры перекрытия пар (пикс, ширина x высота): частые:",collections.Counter((int(a),int(b)) for a,b in wid).most_common(6))
import pickle; pickle.dump((R,pairs),open('a1.pkl','wb'))
