import sys, sqlite3, collections, numpy as np
sys.path.insert(0,'..')
from calc import *
from shapely import from_wkb
c=sqlite3.connect("../A/vectors.gpkg")
P=collections.defaultdict(list)
for fid,nr,g in c.execute("select ogc_fid,nr_user,geom from agrifields order by ogc_fid"):
    P[nr].append((fid,from_wkb(gpb(g))))
sd=[]; nv=[]; fid_gap=[]
for k,v in P.items():
    if len(v)>1 and k!='22490000030364':
        a,b=v[0][1],v[1][1]
        sd.append(area_ha(a.symmetric_difference(b))/area_ha(a)); nv.append((shapely.get_num_coordinates(a),shapely.get_num_coordinates(b))); fid_gap.append(v[1][0]-v[0][0])
sd=np.array(sd); print("симм. разность / площадь: медиана %.2e, p99 %.2e, max %.2e; точное равенство координат (число вершин одинаково): %d из %d"%(np.median(sd),np.quantile(sd,.99),sd.max(),sum(1 for a,b in nv if a==b),len(nv)))
print("разность ogc_fid пары: медиана",int(np.median(fid_gap)),"min",min(fid_gap),"max",max(fid_gap))
