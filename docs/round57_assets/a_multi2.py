import sys, sqlite3, collections
sys.path.insert(0,'..')
from calc import *
from shapely import from_wkb
import shapely
c=sqlite3.connect("../A/vectors.gpkg")
P=collections.defaultdict(list)
for fid,nr,bc,nd,us,uc,sa,g in c.execute("select ogc_fid,nr_user,ball_co,ndohod_d,usname,usern_co,shape_area,geom from agrifields order by ogc_fid"):
    P[nr].append((fid,from_wkb(gpb(g)),sa,len(g)))
multi={k:v for k,v in P.items() if len(v)>1}
cat=collections.Counter(); ex={}
lost_by=collections.Counter(); area_by=collections.Counter()
for k,v in multi.items():
    a,b=v[0][1],v[1][1]
    aa,ab=area_ha(a),area_ha(b); inter=area_ha(a.intersection(b)); un=area_ha(a.union(b))
    if a.equals(b): t='идентичны (ST_Equals)'
    elif inter>0.999*min(aa,ab): t='одна часть внутри другой'
    elif inter>1e-4: t='пересекаются частично'
    else: t='не пересекаются'
    cat[t]+=1; ex.setdefault(t,(k,round(aa,4),round(ab,4),round(inter,4),round(un,4)))
    # потеря площади по сравнению с объединением: показываем первую часть
    lost=un-aa; lost_by[k[:4]]+=lost; area_by[k[:4]]+=un
print(dict(cat)); print(ex)
print("площадь объединения, не покрытая ПЕРВОЙ частью (га) по районам:",{d:round(v,1) for d,v in sorted(lost_by.items())}, "всего",round(sum(lost_by.values()),1))
print("числа сравнения shape_area (м2) в исходных данных у пары (первые 3 неравных):",[ (k,v[0][2],v[1][2]) for k,v in list(multi.items())[:3]])
