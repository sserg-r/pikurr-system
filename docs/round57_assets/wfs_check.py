import json, urllib.request, urllib.parse, sys
B = sys.argv[1]
def wfs(cql, props, layer='pikurr:fields_latest', hits=False):
    q = dict(service='WFS', version='1.1.0', request='GetFeature', typeName=layer, outputFormat='application/json', CQL_FILTER=cql, propertyName=props)
    if hits: q['resultType'] = 'hits'; del q['outputFormat']; del q['propertyName']
    d = urllib.request.urlopen(B + '/geoserver/pikurr/wfs?' + urllib.parse.urlencode(q), timeout=120).read()
    return d.decode() if hits else json.loads(d)
for nr in ['22080000040045', '22080000040095', '22080000141023', '22080000160446', '22490000030364']:
    f = wfs(f"nr_user LIKE '{nr}%'", 'nr_user,valuation,area_ha,stats')['features']
    p = f[0]['properties']; st = json.loads(p['stats']) if isinstance(p['stats'], str) else p['stats']
    print(nr, 'valuation', p['valuation'], 'area_ha', p['area_ha'], 'stats', {k: round(v, 4) for k, v in st.items()})
f = wfs("nr_user LIKE '2212000055%'", 'nr_user,valuation,area_ha')['features']; print('2212000055:', len(f), 'объект(ов)', round(sum(x['properties']['area_ha'] for x in f), 1), 'га', [x['properties']['valuation'] for x in f])
f = wfs("district='2212'", 'nr_user,valuation,area_ha')['features']
import collections; c = collections.Counter(); a = collections.Counter()
for x in f: c[x['properties']['valuation']] += 1; a[x['properties']['valuation']] += x['properties']['area_ha']
print('район 2212:', len(f), 'объектов', round(sum(a.values()), 1), 'га', {k: (c[k], round(a[k], 1)) for k in sorted(c)})
