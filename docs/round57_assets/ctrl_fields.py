import sys, json, sqlite3, collections
sys.path.insert(0,'.')
from calc import area_ha, gpb
from shapely import from_wkb
import shapely
A,N=sys.argv[1],sys.argv[2]
def load(d):
    c=sqlite3.connect(f'file:{d}/vectors.gpkg?mode=ro',uri=True)
    st={r[0]:json.loads(r[1]) for r in c.execute('select fid_ext,stats from assessment')}
    P=collections.defaultdict(list)
    for nr,bc,nd,g in c.execute('select nr_user,ball_co,ndohod_d,geom from agrifields order by ogc_fid'): P[nr].append((bc,nd,from_wkb(gpb(g))))
    return st,P
def val(bc,nd,s):
    v=[float(s.get(str(i),0)) for i in range(6)]; t=sum(v); fr=(v[0]+v[1]+v[2])/t if t else 0
    if fr>0.4 and nd<=0: return 'forest'
    if fr>0.3 and nd>0: return 'clearing'
    if bc>24: return 'tillage'
    return 'meadow'
SA,PA=load(A); SN,PN=load(N)
seen=set(); out=[]
for k in sorted(SA):
    nr=str(k); bc,nd,_=PA[nr][0]; va,vn=val(bc,nd,SA[k]),val(bc,nd,SN[k])
    if va!=vn and (va,vn) not in seen and nr.startswith(('2212','2208','2218','2238')) and len(PA[nr])==1:
        seen.add((va,vn)); out.append((nr,va,vn,SN[k],SA[k]))
    if len(out)>=4: break
for nr,va,vn,sn,sa in out: print(nr,'valuation',va,'->',vn,'| stats N',json.dumps({a:round(b,4) for a,b in sn.items()}),'| stats A',json.dumps({a:round(b,4) for a,b in sa.items()}))
k='22490000030364'; print(k,'area_ha',round(area_ha(PA[k][0][2]),2),'->',round(area_ha(shapely.union_all([p[2] for p in PN[k]])),2))
