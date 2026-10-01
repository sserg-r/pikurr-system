import json, sqlite3, numpy as np, collections
def st(k):
    c=sqlite3.connect(f"file:../{k}/vectors.gpkg?mode=ro",uri=True)
    return {r[0]:json.loads(r[1]) for r in c.execute("select fid_ext,stats from assessment")}
SA,SB=st('A'),st('B')
def mx(a,b): return max(abs(a.get(str(i),0)-b.get(str(i),0)) for i in range(6))
P=collections.defaultdict(list)
for l in open('a3b.jsonl'):
    r=json.loads(l)
    if 'err' in r: continue
    P[r['nr']].append(r)
print("ключей:",len(P),"; частей:",sum(len(v) for v in P.values()),"; частей на ключ:",collections.Counter(len(v) for v in P.values()))
res={}
for lab,S in (('A',SA),('B',SB)):
    ex=0; dist=[]; ownd=[]
    for nr,parts in P.items():
        s=S[int(nr)]
        best=min(((min(mx(p['asc'],s),mx(p['desc'],s)),i) for i,p in enumerate(parts)),key=lambda t:t[0])
        if best[0]<1e-9: ex+=1
        dist.append(best[0]); ownd.append(mx(parts[best[1]]['own'],s))
        res.setdefault(nr,{})[lab]=best[1]
    print(f"{lab}: совпал точно с результатом ETL-функции для одной из частей (в одном из 2 порядков): {ex} из {len(P)}; max|Δ| лучшей части: медиана {np.median(dist):.2g}, макс {max(dist):.3f}")
    print(f"   own лучшей части vs {lab}: медиана {np.median(ownd):.4f}, p90 {np.quantile(ownd,.9):.4f}, >0.1: {sum(x>0.1 for x in ownd)}, >0.3: {sum(x>0.3 for x in ownd)}, max {max(ownd):.3f}")
print("A и B совпали с одной и той же частью у",sum(1 for v in res.values() if v['A']==v['B']),"ключей из",len(res))
