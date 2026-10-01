import sys, json, pickle, sqlite3, collections, numpy as np
sys.path.insert(0,'..')
from calc import *
from shapely import STRtree, from_wkb
from shapely.geometry import box
from shapely.ops import unary_union
R,pairs=pickle.load(open('a1.pkl','rb'))
name_set={r['name'] for r in R}
geo=[box(*r['bounds']) for r in R]
ov=[geo[i].intersection(geo[j]) for i,j,_ in pairs]; ov=[o for o in ov if o.area>0]
U=unary_union(ov)
c=sqlite3.connect("../A/vectors.gpkg")
raz=[(n,from_wkb(gpb(g))) for n,g in c.execute("select n10000,geom from razgrafka")]
rtree=STRtree([g for _,g in raz])
fields={}
for nr,g in c.execute("select nr_user,geom from agrifields order by ogc_fid"):
    fields.setdefault(nr,from_wkb(gpb(g)))
import shapely
shapely.prepare(U)
rows=[]
for nr,g in fields.items():
    idx=rtree.query(g,predicate='intersects')
    fr=[raz[i][0] for i in idx]
    fr_all=len(fr); fr_r=[f for f in fr if f in name_set]
    inO = U.intersects(g)
    a=area_ha(g); ao=area_ha(g.intersection(U)) if inO else 0.0
    rows.append((nr,fr_all,len(fr_r),a,ao))
pickle.dump(rows,open('a1_fields.pkl','wb'))
A=np.array([(r[1],r[2],r[3],r[4]) for r in rows])
tot=A[:,2].sum()
print("участков (уник. nr_user):",len(rows),"общая площадь га:",round(tot,1))
for lab,mask in (("нет листов с растром",A[:,1]==0),("1 лист (с растром)",A[:,1]==1),("2+ листов (с растром)",A[:,1]>=2)):
    n=mask.sum(); a=A[mask,2].sum(); ao=A[mask,3].sum(); ni=(A[mask,3]>0).sum()
    print(f"{lab}: участков {n}; площадь {a:.1f} га; из них пересекают зону перекрытия растров: {ni} уч.; площадь в зоне перекрытия {ao:.1f} га ({100*ao/a if a else 0:.2f}% площади группы)")
print("2+ листов по всем полигонам razgrafka (как в раунде 55):",(A[:,0]>=2).sum())
m=A[:,1]>=2
print("2+ листов: участки с долей площади в перекрытии >0:",(A[m,3]>0).sum(),"; >50%:",(A[m,3]/A[m,2]>0.5).sum(),"; доля площади в перекрытии: медиана",round(float(np.median(A[m,3]/A[m,2])),3),"среднее",round(float((A[m,3].sum()/A[m,2].sum())),3))
