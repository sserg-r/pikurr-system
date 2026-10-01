import sys, sqlite3, collections, hashlib, json
sys.path.insert(0,'..')
from calc import *
from shapely import from_wkb
import shapely, numpy as np
c=sqlite3.connect("../A/vectors.gpkg")
rows=[]
for fid,nr,bc,nd,us,uc,g in c.execute("select ogc_fid,nr_user,ball_co,ndohod_d,usname,usern_co,geom from agrifields order by ogc_fid"):
    rows.append((fid,nr,bc,nd,us,uc,from_wkb(gpb(g))))
P=collections.defaultdict(list)
for r in rows: P[r[1]].append(r)
multi={k:v for k,v in P.items() if len(v)>1}
print("строк agrifields:",len(rows),"ключей:",len(P),"; многочастных ключей:",len(multi),"; полигонов (строк) в них:",sum(len(v) for v in multi.values()),"; распределение числа частей:",dict(collections.Counter(len(v) for v in multi.values())))
# площади
A={}
for k,v in P.items(): A[k]=[area_ha(r[6]) for r in v]
tot_all=sum(sum(a) for a in A.values())
tot_multi=sum(sum(A[k]) for k in multi)
lost=0.0; lost_d=collections.Counter(); tot_d=collections.Counter(); lost_n=0
for k,v in multi.items():
    a=A[k]; shown=a[0]       # DISTINCT ON (nr_user) без сортировки: первая по ogc_fid (проверено на проде отдельно)
    l=sum(a)-shown; lost+=l; lost_d[k[:4]]+=l; lost_n+=len(a)-1
for k in P: tot_d[k[:4]]+=sum(A[k])
print("площадь всех участков (все части), га: %.1f; многочастных: %.1f; НЕ попадающих на витрину частей: %.1f га (%d полигонов), %.2f%% площади всех"%(tot_all,tot_multi,lost,lost_n,100*lost/tot_all))
print("по районам (не на витрине / все части, га):")
for d in sorted(tot_d): print("  ",d,"%.1f / %.1f (%.2f%%)"%(lost_d[d],tot_d[d],100*lost_d[d]/tot_d[d]))
# A2 атрибуты
diff=collections.Counter(); ex=collections.defaultdict(list)
for k,v in multi.items():
    for name,idx in (('ball_co',2),('ndohod_d',3),('usname',4),('usern_co',5)):
        vals={r[idx] for r in v}
        if len(vals)>1:
            diff[name]+=1
            if len(ex[name])<5: ex[name].append((k,[r[idx] for r in v]))
print("\nA2: ключей с различающимся атрибутом среди частей:",dict(diff))
for n,e in ex.items(): print(" ",n,e)
anyk=sum(1 for k,v in multi.items() if len({r[2] for r in v})>1 or len({r[3] for r in v})>1)
print("ключей с различающимся ball_co ИЛИ ndohod_d:",anyk)
# A3 пересечение
ov=0; mx=0; exs=[]
for k,v in multi.items():
    s=sum(area_ha(r[6]) for r in v); u=area_ha(shapely.union_all([r[6] for r in v]))
    d=s-u
    if d>1e-4:
        ov+=1; mx=max(mx,d)
        if len(exs)<3: exs.append((k,round(s,4),round(u,4)))
print("\nA3: ключей, где части пересекаются (площадь объединения < суммы больше чем на 1e-4 га):",ov,"из",len(multi),"; макс. перекрытие, га:",round(mx,4),exs)
json.dump({k:[r[0] for r in v] for k,v in multi.items()},open('multi_keys.json','w'))
