#!/bin/bash
# migrate_2024.sh — импортирует данные 2024 (Витебская обл.) в фронтенд-стек
#
# Запуск:
#   bash migrate_2024.sh                          # локальный стек (порт 5433)
#   FRONTEND_DB_PORT=5435 bash migrate_2024.sh    # серверный стек (порт 5435)
#
# Предварительно: docker compose up -d, папка fromgeobotanyxyz/dump/ присутствует

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUMP_DIR="${SCRIPT_DIR}/fromgeobotanyxyz/dump"
GEODATA_DIR="${SCRIPT_DIR}/data/geodata"

DB_HOST="${FRONTEND_DB_HOST:-localhost}"
DB_PORT="${FRONTEND_DB_PORT:-5433}"
DB_USER="${FRONTEND_DB_USER:-pikurr}"
DB_PASS="${FRONTEND_DB_PASSWORD:-pikurr}"
DB_NAME="${FRONTEND_DB_NAME:-pikurr}"
export PGPASSWORD="$DB_PASS"

GS_URL="${GEOSERVER_URL:-http://localhost:8090/geoserver}"
GS_USER="${GEOSERVER_USER:-admin}"
GS_PASS="${GEOSERVER_PASSWORD:-geoserver}"
GS_WS="${GEOSERVER_WORKSPACE:-pikurr}"

POSTGIS_CTR="${POSTGIS_CONTAINER:-pikurr_local_postgis}"

psql_() { psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"; }

# ─── 1. Схема ────────────────────────────────────────────────────────────────
echo "[1/6] Добавляем колонку valuation в assessment..."
psql_ -c "ALTER TABLE assessment ADD COLUMN IF NOT EXISTS valuation text;"

echo "[2/6] Обновляем view assessment_ready..."
psql_ <<'ENDSQL'
DROP VIEW IF EXISTS assessment_ready;
CREATE OR REPLACE VIEW assessment_ready AS
SELECT
    a.nr_user, a.geom, b.year, b.description, b.stats, b.updated_at,
    ROUND((ST_Area(a.geom::geography) / 10000)::numeric, 2) AS area_ha,
    a.ball_co::float AS ball_co,
    NULL::float AS bzdz,
    CASE
        WHEN b.stats IS NULL THEN b.valuation
        ELSE (
            CASE (SELECT key FROM jsonb_each_text(b.stats::jsonb) ORDER BY value::float DESC LIMIT 1)
                WHEN '0' THEN 'forest'  WHEN '3' THEN 'meadow'
                WHEN '5' THEN 'tillage' ELSE 'clearing'
            END
        )
    END AS valuation
FROM agrifields a
JOIN assessment b ON a.nr_user::bigint = b.fid_ext;
ENDSQL

# ─── 2. Временная база ────────────────────────────────────────────────────────
echo "[3/6] Восстанавливаем дамп во временную базу pikurr_tmp..."
psql_ -c "DROP DATABASE IF EXISTS pikurr_tmp;" 2>/dev/null || true
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -c "CREATE DATABASE pikurr_tmp;"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "pikurr_tmp" -c "CREATE EXTENSION postgis;"

docker cp "${DUMP_DIR}/init/backup.dump" "${POSTGIS_CTR}:/tmp/backup.dump"
docker exec -e PGPASSWORD="$DB_PASS" "$POSTGIS_CTR" \
    pg_restore -U "$DB_USER" -d "pikurr_tmp" /tmp/backup.dump 2>/dev/null || true

# ─── 3. Импорт данных ─────────────────────────────────────────────────────────
echo "[4/6] Импортируем agrifields и assessment через dblink..."

# Создаём temp-скрипт SQL с реальными значениями переменных
TMP_SQL=$(mktemp)
cat > "$TMP_SQL" <<ENDSQL
CREATE EXTENSION IF NOT EXISTS dblink;

INSERT INTO agrifields (objectid, usname, num_rab, ball_plpoc, ball_co, ndohod_d, nr_user, usern_co, landcode, shape_area, dateco, shape_leng, geom)
SELECT objectid, usname, num_rab::integer, ball_plpoc, ball_co, ndohod_d, nr_user, usern_co, landcode::integer, shape_area, dateco, shape_leng, geom
FROM dblink(
    'host=localhost dbname=pikurr_tmp user=${DB_USER} password=${DB_PASS}',
    'SELECT objectid, usname, num_rab, ball_plpoc, ball_co, ndohod_d, nr_user, usern_co, landcode, shape_area, dateco, shape_leng, geom FROM agrifields'
) AS t(objectid double precision, usname varchar(250), num_rab double precision,
    ball_plpoc numeric(24,15), ball_co numeric(24,15), ndohod_d numeric(24,15),
    nr_user varchar(15), usern_co varchar(10), landcode double precision,
    shape_area numeric(24,15), dateco varchar(24), shape_leng numeric(24,15), geom geometry);

INSERT INTO assessment (id, fid_ext, year, description, stats, valuation, updated_at)
SELECT
    (SELECT COALESCE(MAX(id),0) FROM assessment) + ROW_NUMBER() OVER () AS id,
    nr_user::bigint AS fid_ext,
    year::integer,
    description,
    NULL AS stats,
    valuation,
    NOW() AS updated_at
FROM dblink(
    'host=localhost dbname=pikurr_tmp user=${DB_USER} password=${DB_PASS}',
    'SELECT nr_user, year, description, valuation FROM assessment_ready'
) AS t(nr_user varchar(15), year smallint, description text, valuation text);

DELETE FROM assessment WHERE fid IN (
    SELECT fid FROM (
        SELECT fid, ROW_NUMBER() OVER (PARTITION BY fid_ext, year ORDER BY fid) AS rn
        FROM assessment
    ) t WHERE rn > 1
);

SELECT year, COUNT(*) AS parcels FROM assessment_ready GROUP BY year ORDER BY year;
ENDSQL
# Expand shell variables into the SQL file
eval "cat <<ENVSQL
$(cat "$TMP_SQL")
ENVSQL" > "${TMP_SQL}.expanded"
psql_ -f "${TMP_SQL}.expanded"
rm -f "$TMP_SQL" "${TMP_SQL}.expanded"

# ─── 4. Растровые данные ──────────────────────────────────────────────────────
echo "[5/6] Копируем TIF 2024 ($(ls "${DUMP_DIR}/2024/"*.tif | wc -l) файлов)..."
mkdir -p "${GEODATA_DIR}/2024"
cp "${DUMP_DIR}/2024/"*.tif "${GEODATA_DIR}/2024/"
cp "${DUMP_DIR}/2024/2024."* "${GEODATA_DIR}/2024/"
echo "Готово: ${GEODATA_DIR}/2024/"

# ─── 5. GeoServer ─────────────────────────────────────────────────────────────
echo "[6/6] Создаём image_assessment_2024 в GeoServer..."
curl -sf -u "${GS_USER}:${GS_PASS}" \
  -X POST "${GS_URL}/rest/workspaces/${GS_WS}/coveragestores" \
  -H "Content-Type: application/json" \
  -d "{\"coverageStore\":{\"name\":\"image_assessment_2024\",\"workspace\":{\"name\":\"${GS_WS}\"},\"type\":\"ImageMosaic\",\"enabled\":true,\"url\":\"file:///mnt/data/geodata/2024/\"}}" \
  && echo "  Store: OK" || echo "  Store: вероятно уже существует"

curl -sf -u "${GS_USER}:${GS_PASS}" \
  -X POST "${GS_URL}/rest/workspaces/${GS_WS}/coveragestores/image_assessment_2024/coverages" \
  -H "Content-Type: application/json" \
  -d '{"coverage":{"name":"image_assessment_2024","nativeName":"2024","nativeCoverageName":"2024","enabled":true}}' \
  && echo "  Coverage: OK" || echo "  Coverage: вероятно уже существует"

curl -sf -u "${GS_USER}:${GS_PASS}" \
  -X PUT "${GS_URL}/rest/layers/${GS_WS}:image_assessment_2024" \
  -H "Content-Type: application/json" \
  -d "{\"layer\":{\"defaultStyle\":{\"name\":\"${GS_WS}:raster_vegetation\",\"workspace\":\"${GS_WS}\"}}}" \
  && echo "  Style: OK"

# ─── Очистка ──────────────────────────────────────────────────────────────────
echo "Очистка временной базы..."
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" \
    -c "DROP DATABASE IF EXISTS pikurr_tmp;" 2>/dev/null || true

echo ""
echo "=== Миграция завершена ==="
echo "Обновите React-образ: docker compose build react-client && docker compose up -d react-client"
