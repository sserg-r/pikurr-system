import sys, sqlite3, numpy as np
sys.path.insert(0,'..')
from calc import *
from shapely import from_wkb, STRtree
c=sqlite3.connect("../A/vectors.gpkg")
raz=[(n,from_wkb(gpb(g))) for n,g in c.execute("select n10000,geom from razgrafka")]
G=[g for _,g in raz]; tr=STRtree(G)
ov=[]; touch=0
for i,g in enumerate(G):
    for j in tr.query(g,predicate='intersects'):
        if j>i:
            a=area_ha(g.intersection(G[j]))
            if a>0: ov.append((a,raz[i][0],raz[j][0]))
            else: touch+=1
ov.sort(reverse=True)
print("пар полигонов, соприкасающихся/пересекающихся:",touch+len(ov),"; с ненулевой площадью пересечения:",len(ov)); print(ov[:5])
# общие вершины соседей?
print("пример полигона:",list(G[0].geoms[0].exterior.coords)[:5])
