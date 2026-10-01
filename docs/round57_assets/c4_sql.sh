set -e
cd /tmp/pikurr_r57
PS="docker exec -i pikurr_r57_tmpdb psql -q -U postgres -v ON_ERROR_STOP=1"
sig() { docker exec pikurr_r57_tmpdb psql -At -U postgres -d $1 -c "SELECT c.relname||'.'||a.attname||' '||format_type(a.atttypid,a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid WHERE c.relname IN ('assessment_ready','assessment_ready_latest','levelsagg_ready') AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1"; }
DB=db_v34
docker exec pikurr_r57_tmpdb psql -q -U postgres -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB TEMPLATE db_r4"
echo "== v3: применение схемы версии 3"
$PS -d $DB < create_assessment_schema_v3.sql >/dev/null 2>&1
docker exec pikurr_r57_tmpdb psql -At -U postgres -d $DB -c "SELECT relname, obj_description(oid,'pg_class') FROM pg_class WHERE relname IN ('assessment_ready','assessment_ready_latest','levelsagg_ready') ORDER BY 1"
sig $DB > sig_v3.txt
$PS -d $DB -c "CREATE TABLE snap_v3 AS SELECT nr_user, year, md5(ST_AsEWKB(geom)::text) h, area_ha, bzdz, valuation, stats FROM assessment_ready" -c "CREATE TABLE snap_v3_lev AS SELECT md5(string_agg(usname||'|'||usern_co||'|'||rn, ',' ORDER BY usname,usern_co,rn)) h, count(*) n FROM levelsagg_ready"
docker exec pikurr_r57_tmpdb psql -At -U postgres -d $DB -c "SELECT 'v3 строк assessment_ready', count(*), count(distinct nr_user) FROM assessment_ready"
echo "== миграция как в deliver.ensure_assessment_schema: DROP объектов по relkind, затем SQL версии 4"
$PS -d $DB -c "DROP MATERIALIZED VIEW IF EXISTS assessment_ready CASCADE" -c "DROP MATERIALIZED VIEW IF EXISTS levelsagg_ready CASCADE"
$PS -d $DB < create_assessment_schema.sql >/dev/null 2>&1
docker exec pikurr_r57_tmpdb psql -At -U postgres -d $DB -c "SELECT relname, obj_description(oid,'pg_class'), relkind FROM pg_class WHERE relname IN ('assessment_ready','assessment_ready_latest','levelsagg_ready') ORDER BY 1"
sig $DB > sig_v4.txt
echo "столбцы и типы представлений v3 = v4:"; diff sig_v3.txt sig_v4.txt && echo "ИДЕНТИЧНО ($(wc -l < sig_v4.txt) столбцов)"
docker exec -i pikurr_r57_tmpdb psql -At -U postgres -d $DB <<'SQL'
SELECT 'v4 строк assessment_ready', count(*), count(distinct nr_user) FROM assessment_ready;
SELECT 'v4 assessment_ready_latest', count(*), count(distinct nr_user) FROM assessment_ready_latest;
SELECT 'levelsagg_ready v3=v4', (SELECT h FROM snap_v3_lev)=(SELECT md5(string_agg(usname||'|'||usern_co||'|'||rn, ',' ORDER BY usname,usern_co,rn)) FROM levelsagg_ready), (SELECT n FROM snap_v3_lev), count(*) FROM levelsagg_ready;
SELECT 'однокомпонентные: геометрия/area/bzdz/valuation/stats v3=v4', count(*), sum((v3.h=v4.h AND v3.area_ha=v4.area_ha AND v3.bzdz=v4.bzdz AND v3.valuation IS NOT DISTINCT FROM v4.valuation AND v3.stats IS NOT DISTINCT FROM v4.stats)::int)
 FROM snap_v3 v3 JOIN assessment_ready v4 USING (nr_user, year) WHERE v4.nr_user IN (SELECT nr_user FROM agrifields GROUP BY nr_user HAVING count(*)=1);
SELECT 'многочастные: area_ha(view v4) = ROUND(ST_Area(ST_Union)/10000,2)', count(*), sum((v.area_ha = ROUND((ST_Area(u.g::geography)/10000)::numeric,2))::int), max(abs(v.area_ha - ROUND((ST_Area(u.g::geography)/10000)::numeric,2)))
 FROM assessment_ready v JOIN (SELECT nr_user, ST_Union(geom) g FROM agrifields GROUP BY nr_user HAVING count(*)>1) u USING (nr_user);
SELECT 'реальный многочастный 22490000030364: v3 area_ha', (SELECT area_ha FROM snap_v3 WHERE nr_user='22490000030364'), 'v4', (SELECT area_ha FROM assessment_ready WHERE nr_user='22490000030364'), 'сумма частей га', (SELECT ROUND((sum(ST_Area(geom::geography))/10000)::numeric,2) FROM agrifields WHERE nr_user='22490000030364');
SELECT 'типы геометрии v4', GeometryType(geom), count(*) FROM assessment_ready GROUP BY 2;
SELECT 'ИНДЕКСЫ', count(*) FROM pg_indexes WHERE tablename IN ('assessment_ready','assessment_ready_latest','levelsagg_ready');
SQL
echo "== C5: чистая база: bootstrap -> create_assessment_schema (v4) -> вставка формы save_db -> REFRESH"
docker exec pikurr_r57_tmpdb psql -q -U postgres -c "DROP DATABASE IF EXISTS db_clean" -c "CREATE DATABASE db_clean"
docker exec pikurr_r57_tmpdb psql -q -U postgres -d db_clean -c "CREATE EXTENSION IF NOT EXISTS postgis"
$PS -d db_clean < bootstrap_empty_schema.sql >/dev/null 2>&1
$PS -d db_clean < create_assessment_schema.sql >/dev/null 2>&1
docker exec pikurr_r57_tmpdb psql -At -U postgres -d db_clean -c "SELECT relname, relkind, obj_description(oid,'pg_class') FROM pg_class WHERE relname IN ('assessment_ready','assessment_ready_latest','levelsagg_ready') ORDER BY 1"
docker exec pikurr_r57_tmpdb psql -At -U postgres -d db_r4 -c "COPY (SELECT * FROM agrifields WHERE nr_user IN ('22490000030364','22380000160157','22380000160158') ) TO STDOUT" | docker exec -i pikurr_r57_tmpdb psql -q -U postgres -d db_clean -c "COPY agrifields FROM STDIN" 
docker exec -i pikurr_r57_tmpdb psql -q -U postgres -d db_clean <<'SQL'
INSERT INTO assessment (fid_ext, year, stats, updated_at) VALUES (22490000030364, 2025, '{"0": 0.5, "5": 0.5}', now()), (22380000160157, 2025, '{"3": 1.0}', now()), (22380000160158, 2025, '{"0": 1.0}', now()) ON CONFLICT (fid_ext, year) DO UPDATE SET stats = EXCLUDED.stats, updated_at = EXCLUDED.updated_at;
REFRESH MATERIALIZED VIEW assessment_ready; REFRESH MATERIALIZED VIEW assessment_ready_latest; REFRESH MATERIALIZED VIEW levelsagg_ready;
SQL
docker exec pikurr_r57_tmpdb psql -At -U postgres -d db_clean -c "SELECT 'строк assessment_ready', count(*) FROM assessment_ready" -c "SELECT 'latest', count(*) FROM assessment_ready_latest" -c "SELECT 'levelsagg', count(*) FROM levelsagg_ready" -c "SELECT 'ispopulated', matviewname, ispopulated FROM pg_matviews ORDER BY 2" -c "SELECT nr_user, valuation, area_ha FROM assessment_ready ORDER BY 1"
