SELECT DISTINCT r.n10000
FROM razgrafka r
JOIN agrifields a ON ST_Intersects(r.geom, a.geom);