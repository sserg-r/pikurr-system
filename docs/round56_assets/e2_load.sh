set -e
SRC="docker exec pikurr-system-db-1 sh -c"
SHEETS="'N-35-10-А-в-2','N-35-10-А-г-1','N-35-10-А-а-4','N-35-10-А-б-3'"
Q_F="SELECT a.* FROM agrifields a WHERE EXISTS (SELECT 1 FROM razgrafka r WHERE r.n10000 IN ($SHEETS) AND a.geom && r.geom)"
Q_R="SELECT r.* FROM razgrafka r WHERE r.n10000 IN ($SHEETS) OR EXISTS (SELECT 1 FROM ($Q_F) f WHERE ST_Intersects(f.geom, r.geom))"
Q_T="SELECT * FROM trapeze_serv WHERE name IN ($SHEETS)"
for pair in "agrifields|$Q_F" "razgrafka|$Q_R" "trapeze_serv|$Q_T"; do
  t=${pair%%|*}; q=${pair#*|}
  docker exec pikurr-system-db-1 psql -U postgres -d pikurr_db -c "COPY ($q) TO STDOUT" | docker exec -i pikurr_r56_tmpdb psql -q -U postgres -d pikurr_db -v ON_ERROR_STOP=1 -c "COPY $t FROM STDIN"
done
docker exec pikurr_r56_tmpdb psql -q -U postgres -d pikurr_db -c "ANALYZE agrifields; ANALYZE razgrafka;" -c "select (select count(*) from agrifields) f,(select count(*) from razgrafka) r,(select count(*) from trapeze_serv) t,(select count(*) from assessment) a"
