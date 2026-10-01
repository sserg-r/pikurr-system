import sys, json, itertools, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0,'/app')
from pathlib import Path
from src.utils.postclassify import calculate_zonal_stats
year_dir=Path('/data_output/predictions/predictions_final/2025')
def close(a,b,tol=1e-9):
    return set(a)==set(b) and all(abs(a[k]-b[k])<tol for k in a)
for o in json.load(sys.stdin):
    row={'nr':o['nr'],'nframes':len(o['frames']),'perms':[]}
    for perm in itertools.permutations(o['frames']):
        paths=[str(year_dir/f"{f}.tif") for f in perm if (year_dir/f"{f}.tif").exists()]
        s=calculate_zonal_stats(json.dumps(o['geom']),paths)
        row['perms'].append(('A' if close(s,o['A']) else '')+('B' if close(s,o['B']) else '') or '-')
    row['A==B']=close(o['A'],o['B'])
    print(json.dumps(row,ensure_ascii=False),flush=True)
