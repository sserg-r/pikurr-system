import json, sqlite3, numpy as np, collections, sys
sys.path.insert(0,'..')
def st(k):
    c=sqlite3.connect(f"file:../{k}/vectors.gpkg?mode=ro",uri=True)
    return {r[0]:json.loads(r[1]) for r in c.execute("select fid_ext,stats from assessment")}
SA,SB=st('A'),st('B')
c=sqlite3.connect("file:../A/vectors.gpkg?mode=ro",uri=True)
AF={}
for nr,bc,nd in c.execute("select nr_user,ball_co,ndohod_d from agrifields order by ogc_fid"): AF.setdefault(nr,(bc,nd))
def val(bc,nd,s):
    v=[float(s.get(str(i),0)) for i in range(6)]; t=sum(v); fr=(v[0]+v[1]+v[2])/t if t else 0
    if fr>0.4 and nd<=0: return 'forest'
    if fr>0.3 and nd>0: return 'clearing'
    if bc>24: return 'tillage'
    return 'meadow'
def mx(a,b): return max(abs(a.get(str(i),0)-b.get(str(i),0)) for i in range(6))
def cl5(a): return a.get('5',0)
R=[json.loads(l) for l in open('a3.jsonl')]
R=[r for r in R if 'err' not in r]
errs=sum(1 for l in open('a3.jsonl') if '"err"' in l)
multi=[r for r in R if r['nfr']>=2]; single=[r for r in R if r['nfr']==1]
print("результатов",len(R),"ошибок",errs,"; на 2+ листах:",len(multi),"; контроль 1 лист:",len(single))
def quant(x): 
    x=np.array(x); return dict(медиана=round(float(np.median(x)),4),p90=round(float(np.quantile(x,.9)),4),p99=round(float(np.quantile(x,.99)),4),max=round(float(x.max()),4),gt01=int((x>0.1).sum()),gt03=int((x>0.3).sum()),gt1e6=int((x>1e-6).sum()))
print("\n== КОНТРОЛЬ: 1 лист ==")
for lab,f in (("own vs A",lambda r:mx(r['own'],SA[int(r['nr'])])),("own vs B",lambda r:mx(r['own'],SB[int(r['nr'])])),("A vs B",lambda r:mx(SA[int(r['nr'])],SB[int(r['nr'])])),("own vs asc(ETL-функция)",lambda r:mx(r['own'],r['asc']))):
    d=[f(r) for r in single]; print(f"{lab}: n={len(d)}",quant(d))
print("\n== 2+ листов (nr_user без многочастных) ==")
D={}
for lab,f in (("own vs A",lambda r:mx(r['own'],SA[int(r['nr'])])),("own vs B",lambda r:mx(r['own'],SB[int(r['nr'])])),("A vs B",lambda r:mx(SA[int(r['nr'])],SB[int(r['nr'])]))):
    D[lab]=[f(r) for r in multi]; print(f"{lab}: n={len(multi)}",quant(D[lab]))
print("среднее max|Δ|: own–A %.4f, own–B %.4f, A–B %.4f"%tuple(np.mean(D[k]) for k in ("own vs A","own vs B","A vs B")))
print("средний |Δ доли класса 5|: own–A %.4f, own–B %.4f"%(np.mean([abs(cl5(r['own'])-cl5(SA[int(r['nr'])])) for r in multi]),np.mean([abs(cl5(r['own'])-cl5(SB[int(r['nr'])])) for r in multi])))
print("кто ближе к own: A ближе у %d, B ближе у %d, равно %d"%(sum(a<b for a,b in zip(D['own vs A'],D['own vs B'])),sum(b<a for a,b in zip(D['own vs A'],D['own vs B'])),sum(a==b for a,b in zip(D['own vs A'],D['own vs B']))))
ch=collections.Counter(); chtr=collections.Counter()
for r in multi:
    k=int(r['nr']); bc,nd=AF[r['nr']]
    vo,va,vb=val(bc,nd,r['own']),val(bc,nd,SA[k]),val(bc,nd,SB[k])
    ch['own≠A']+=vo!=va; ch['own≠B']+=vo!=vb; ch['A≠B']+=va!=vb
    if vo!=va: chtr[(va,vo)]+=1
print("смена сценария (valuation):",dict(ch),"из",len(multi)); print("A→own:",dict(chtr))
# сэмпл asc/desc
sub=[r for r in multi if 'asc' in r]
print("\n== подвыборка с ETL-функцией в двух порядках листов (asc/desc), n=%d =="%len(sub))
def eq(a,b): return mx(a,b)<1e-9
print("asc==desc: %d из %d"%(sum(eq(r['asc'],r['desc']) for r in sub),len(sub)))
for lab,k in (("A",SA),("B",SB)):
    print(f"{lab}: совпал с asc {sum(eq(r['asc'],k[int(r['nr'])]) for r in sub)}, с desc {sum(eq(r['desc'],k[int(r['nr'])]) for r in sub)}, с одним из двух {sum(eq(r['asc'],k[int(r['nr'])]) or eq(r['desc'],k[int(r['nr'])]) for r in sub)}")
da=[mx(r['own'],r['asc']) for r in sub]; dd=[mx(r['own'],r['desc']) for r in sub]; dab=[mx(r['asc'],r['desc']) for r in sub]
print("own vs asc",quant(da)); print("own vs desc",quant(dd)); print("asc vs desc",quant(dab))
