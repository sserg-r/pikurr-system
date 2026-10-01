import json, random, io, subprocess, urllib.request, urllib.parse, sys
from PIL import Image
S=json.load(open('a4_samples.json'))
cand=[s for s in S if s['a_poly']!=s['b_poly']]
random.seed(11); random.shuffle(cand)
# разные пары/районы
sel=[]; seen=set()
for s in cand:
    k=(s['a'][:12]); 
    if k in seen: continue
    seen.add(k); sel.append(s)
    if len(sel)==30: break
tt=str.maketrans({'А':'A','Б':'B','В':'V','Г':'G','а':'a','б':'b','в':'v','г':'g'})
# порядок гранул в индексе мозаики (shapefile FID), VPS 2025.shp
out=subprocess.run(['ogrinfo','vps/2025.shp','-al','-geom=NO','-q'],capture_output=True,text=True).stdout
loc=[l.split('=')[1].strip() for l in out.splitlines() if 'location (String)' in l]
order={n:i for i,n in enumerate(loc)}
col={(0x4e,0x76,0x26):1,(0x30,0xb6,0x46):2,(0xac,0xf1,0x89):3,(0xde,0xff,0xcf):4,(0xf8,0xf5,0xc4):5,(0xcb,0xa2,0x7b):6}
res=[]
px_lon=1.0728836059570312e-05; px_lat=5.996e-06
for s in sel:
    lon,lat=s['lon'],s['lat']; n=9
    bbox=(lon-n/2*px_lon,lat-n/2*px_lat,lon+n/2*px_lon,lat+n/2*px_lat)
    url="https://geobotany.of.by/geoserver/pikurr/wms?"+urllib.parse.urlencode(dict(service='WMS',version='1.1.1',request='GetMap',layers='pikurr:image_assessment',styles='',format='image/png',transparent='true',srs='EPSG:4326',width=n,height=n,bbox=",".join(f"{v:.9f}" for v in bbox)))
    d=urllib.request.urlopen(url,timeout=60).read()
    im=Image.open(io.BytesIO(d)).convert('RGBA'); c=im.getpixel((n//2,n//2))
    cls=col.get(c[:3],None) if c[3]>0 else 0
    na,nb=s['a'].translate(tt)+'.tif',s['b'].translate(tt)+'.tif'
    own='A' if s['a_poly'] else 'B'
    res.append((cls,s['val_a'],s['val_b'],own,order.get(na),order.get(nb)))

import collections
c=collections.Counter()
for cls,va,vb,own,ia,ib in res:
    win='A' if cls==va else ('B' if cls==vb else 'иное')
    c['n']+=1; c['значение = одному из двух растров']+= win!='иное'
    c['совпало со «своим» листом (полигон)']+= (win==own)
    low='A' if ia<ib else 'B'
    c['совпало с листом с меньшим номером в индексе']+= (win==low)
print(dict(c))
