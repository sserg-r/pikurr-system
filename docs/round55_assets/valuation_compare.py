import sys; sys.path.insert(0,'.')
from calc import *
import collections, pickle
rows=load_af("A")   # agrifields identical A/B (проверено)
first={}; dups=collections.defaultdict(list)
for fid,nr,bc,nd,g in rows:
    dups[nr].append((fid,bc,nd,g))
# dedupe: variant1 first by ogc_fid, variant2 last
def pick(v):
    out={}
    for nr,l in dups.items():
        fid,bc,nd,g=l[0] if v==0 else l[-1]
        out[nr]=(bc,nd,g)
    return out
def stats(k):
    c=sqlite3.connect(f"file:{k}/vectors.gpkg?mode=ro",uri=True)
    return {r[0]:(json.loads(r[1]) if r[1] else None) for r in c.execute("select fid_ext,stats from assessment")}
def val(bc,nd,st):
    if st is None: return None
    s=[float(st.get(str(i),0) or 0) for i in range(6)]
    tot=sum(s); frac=(s[0]+s[1]+s[2])/tot if tot else None
    if frac is not None and frac>0.4 and nd<=0: return 'forest'
    if frac is not None and frac>0.3 and nd>0: return 'clearing'
    if bc>24: return 'tillage'
    return 'meadow'
S={k:stats(k) for k in "AB"}
res={}
areas={}
for v in (0,1):
    af=pick(v)
    for nr,(bc,nd,g) in af.items():
        if nr.startswith('2212') and (v,nr) not in areas:
            pass
    for k in "AB":
        m={}
        for nr,(bc,nd,g) in af.items():
            fe=int(nr)
            if fe in S[k]:
                m[nr]=val(bc,nd,S[k][fe])
        res[(v,k)]=m
# площади: только район 2212
ar={}
for nr,(bc,nd,g) in pick(0).items():
    if nr.startswith('2212'): ar[(0,nr)]=round(area_ha(from_wkb(gpb(g))),2)
for nr,(bc,nd,g) in pick(1).items():
    if nr.startswith('2212'): ar[(1,nr)]=round(area_ha(from_wkb(gpb(g))),2)
for v in (0,1):
    print("== вариант дедупа", "первая" if v==0 else "последняя", "строка по ogc_fid")
    for k in "AB":
        m=res[(v,k)]
        d={nr:s for nr,s in m.items() if nr.startswith('2212')}
        tot=sum(ar[(v,nr)] for nr in d)
        by=collections.defaultdict(lambda:[0,0.0])
        for nr,s in d.items(): by[s][0]+=1; by[s][1]+=ar[(v,nr)]
        print(k,"район 2212:",len(d),"объектов, %.1f га"%tot, {s:(n,round(a,1)) for s,(n,a) in sorted(by.items())})
        p=[(nr,s,ar[(v,nr)]) for nr,s in d.items() if nr.startswith('2212000055')]
        print(k,"2212000055:",len(p),"объект(ов)",round(sum(x[2] for x in p),1),"га",[x[1] for x in p])
    ch=[(nr,res[(v,'A')][nr],res[(v,'B')][nr]) for nr in res[(v,'A')] if res[(v,'A')][nr]!=res[(v,'B')].get(nr)]
    print("смена сценария:",len(ch),collections.Counter((a,b) for _,a,b in ch))
pickle.dump((res,ar),open('res.pkl','wb'))
# общий (все районы, по всем 55784 assessment)
