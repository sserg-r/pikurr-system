set -e
cd /tmp/pikurr_r57
docker run -d --name pikurr_r57_tmpdb --network pikurr-system_default --tmpfs /var/lib/postgresql/data:rw -e POSTGRES_PASSWORD=r57test -e POSTGRES_DB=base postgis/postgis:15-3.3 >/dev/null
for i in $(seq 1 60); do sleep 1; docker exec pikurr_r57_tmpdb pg_isready -U postgres -d base >/dev/null 2>&1 && [ $i -gt 6 ] && break; done
P="docker exec -i pikurr_r57_tmpdb psql -q -U postgres -v ON_ERROR_STOP=1"
S1="'N-35-34-В-а-4','N-35-34-В-а-3','N-35-34-В-а-2','N-35-34-В-а-1','N-35-34-В-б-3','N-35-34-В-б-1','N-35-34-А-в-4','N-35-34-А-в-3'"
S2="'N-35-34-Б-г-1','N-35-34-Б-в-2','N-35-34-Б-б-3'"
Q_F="SELECT a.* FROM agrifields a WHERE EXISTS (SELECT 1 FROM razgrafka r WHERE r.n10000 IN ($S1) AND a.geom && r.geom)
UNION
SELECT a.* FROM agrifields a WHERE a.nr_user IN (SELECT nr_user FROM agrifields x WHERE EXISTS (SELECT 1 FROM razgrafka r WHERE r.n10000 IN ($S2) AND x.geom && r.geom) GROUP BY nr_user HAVING count(*)>1 ORDER BY nr_user LIMIT 60)"
Q_R="SELECT r.* FROM razgrafka r WHERE r.n10000 IN ($S1) OR EXISTS (SELECT 1 FROM ($Q_F) f WHERE ST_Intersects(f.geom, r.geom))"
Q_T="SELECT * FROM trapeze_serv WHERE name IN ($S1)"
docker exec pikurr-system-db-1 pg_dump -U postgres -d pikurr_db -s -t agrifields -t razgrafka -t assessment -t trapeze_serv | $P -d base >/dev/null
for pair in "agrifields|$Q_F" "razgrafka|$Q_R" "trapeze_serv|$Q_T"; do
  t=${pair%%|*}; q=${pair#*|}
  docker exec pikurr-system-db-1 psql -U postgres -d pikurr_db -c "COPY ($q) TO STDOUT" | $P -d base -c "COPY $t FROM STDIN"
done
$P -d base -c "ANALYZE" -c "select (select count(*) from agrifields) f,(select count(distinct nr_user) from agrifields) k,(select count(*) from razgrafka) r,(select count(*) from trapeze_serv) t"
for d in r0 r2 r4 c1o c1n c3o c3n; do docker exec pikurr_r57_tmpdb psql -q -U postgres -c "CREATE DATABASE db_$d TEMPLATE base"; done
docker exec pikurr_r57_tmpdb psql -At -U postgres -c "select datname from pg_database where datname like 'db_%'" | tr '\n' ' '
