import sqlite3, json, math, csv, sys
import numpy as np
from shapely import from_wkb
import shapely
a=6378137.0; f=1/298.257223563; e2=f*(2-f); e=math.sqrt(e2)
def q(phi):
    s=math.sin(phi); return (1-e2)*(s/(1-e2*s*s) - (1/(2*e))*math.log((1-e*s)/(1+e*s)))
qp=q(math.pi/2)
def qv(phi):
    s=np.sin(phi); return (1-e2)*(s/(1-e2*s*s) - (1/(2*e))*np.log((1-e*s)/(1+e*s)))
def area_ha(geom):
    # equal-area (authalic) cylindrical: x=a*lon, y=a*q/2
    g=shapely.transform(geom, lambda c: np.column_stack([np.radians(c[:,0])*a, a*qv(np.radians(c[:,1]))/2]))
    return abs(g.area)/10000
def gpb(blob):
    flags=blob[3]; env=(flags>>1)&7; n={0:0,1:32,2:48,3:48,4:64}[env]
    return blob[8+n:]
def load_af(k):
    c=sqlite3.connect(f"file:{k}/vectors.gpkg?mode=ro",uri=True)
    rows=[]
    for fid,nr,bc,nd,g in c.execute("select ogc_fid,nr_user,ball_co,ndohod_d,geom from agrifields order by ogc_fid"):
        rows.append((fid,nr,bc,nd,g))
    return rows
