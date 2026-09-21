-- Заглушки для чистого инстанса (round23, задача 3).
--
-- Запускать ОДИН РАЗ, вручную, ПОСЛЕ поднятия PostGIS и ДО первого старта
-- GeoServer на новом развёртывании — см. docs/deploy-repikurr-vps.md,
-- раздел "Первая доставка на чистый инстанс".
--
-- Без этого GeoServer при первом обращении к слою pikurr:fields (virtual
-- table с фиксированной SQL "SELECT * FROM assessment_ready") обнаруживал
-- отсутствие этого view и уходил в агрессивный (тысячи запросов/сек) цикл
-- опроса, насыщая пул соединений PostGIS и мешая первому реальному импорту
-- пройти (round22, живая находка на geobotany.of.by).
--
-- Настоящую схему создаёт create_assessment_schema.sql при первой
-- доставке — он сам заменит эту заглушку: assessment (CREATE TABLE IF NOT
-- EXISTS — не тронет, если уже создана здесь пустой) и assessment_ready
-- (безусловный DROP VIEW ... CASCADE, если это обычный VIEW, → CREATE
-- MATERIALIZED VIEW) — миграционный путь уже заложен в основном скрипте
-- именно под этот случай "было обычным view, стало материализованным".

CREATE TABLE IF NOT EXISTS assessment (
    id SERIAL PRIMARY KEY,
    fid_ext BIGINT NOT NULL,
    year INTEGER NOT NULL,
    stats JSONB,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    valuation TEXT,
    CONSTRAINT assessment_fid_year_key UNIQUE (fid_ext, year)
);

DROP VIEW IF EXISTS assessment_ready_latest;
DROP MATERIALIZED VIEW IF EXISTS assessment_ready_latest;
DROP VIEW IF EXISTS assessment_ready;
DROP MATERIALIZED VIEW IF EXISTS assessment_ready;

-- Пустая заглушка — не настоящая логика, только чтобы имя существовало,
-- отвечало на запросы нулём строк и не давало GeoServer'у повода для
-- бесконечного опроса. Набор колонок близок к реальному представлению —
-- чтобы GeoServer, если успеет закэшировать featuretype по заглушке,
-- не разошёлся сильно с реальной схемой после первой доставки.
-- round25, блок C3: типы колонок сверены с create_assessment_schema.sql
-- построчно — `geom` теперь с явным типом/SRID (иначе GeoServer, если
-- успевает закэшировать featuretype по заглушке, подставляет служебный
-- placeholder-код EPSG:404000, round24 задача 6), `stats` — varchar
-- (реальная таблица assessment хранит его как varchar, не jsonb — само
-- значение это JSON-текст, но колонка типизирована как строка).
CREATE VIEW assessment_ready AS
SELECT
    NULL::varchar                    AS nr_user,
    NULL::varchar(4)                 AS district,
    NULL::geometry(MultiPolygon,4326) AS geom,
    NULL::integer                    AS year,
    NULL::text                       AS description,
    NULL::varchar                    AS stats,
    NULL::timestamp                  AS updated_at,
    NULL::numeric                    AS area_ha,
    NULL::double precision           AS ball_co,
    NULL::text                       AS bzdz,
    NULL::text                       AS valuation
WHERE FALSE;

CREATE VIEW assessment_ready_latest AS
SELECT * FROM assessment_ready;
