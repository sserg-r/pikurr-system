-- round27, A2: версия схемы объектов assessment_ready/levelsagg_ready.
-- CREATE MATERIALIZED VIEW IF NOT EXISTS молча пропускает смену
-- определения уже существующего объекта (обнаружено фактом round26,
-- B5) — deliver.py сравнивает эту версию (COMMENT ON MATERIALIZED VIEW
-- в конце файла) с версией, записанной в коде, и пересоздаёт объект
-- только при расхождении. Поднимать это число при ЛЮБОЙ смене SELECT
-- в assessment_ready/levelsagg_ready ниже.
-- SCHEMA_VERSION = 2

-- 1. Таблица результатов оценки
CREATE TABLE IF NOT EXISTS assessment (
    id SERIAL PRIMARY KEY,
    fid_ext BIGINT NOT NULL,       -- ID пользователя/поля из agrifields
    year INTEGER NOT NULL,         -- Год оценки
    stats JSONB,                   -- Статистика в JSON (новые данные)
    description TEXT,              -- HTML таблица (для GeoServer / legacy)
    updated_at TIMESTAMP DEFAULT NOW(),
    valuation TEXT,                -- Категория (legacy: если stats IS NULL)

    CONSTRAINT assessment_fid_year_key UNIQUE (fid_ext, year)
);

CREATE INDEX IF NOT EXISTS idx_assessment_fid_year ON assessment (fid_ext, year);

-- Колонка valuation отсутствует в ETL-схеме (добавлена только на фронтенде для legacy-данных).
-- Гарантируем её наличие на случай если таблица уже создана без неё (напр. через ogr2ogr).
ALTER TABLE assessment ADD COLUMN IF NOT EXISTS valuation TEXT;

-- 2. Представление для публикации в GeoServer
-- Соединяет геометрию полей с результатами оценки и вычисляет производные колонки.
--
-- Классы сегментации (stats JSON keys):
--   0 = forest   1 = bushes   2 = bushy   3 = meadows   4 = other   5 = tillage
--
-- Маппинг в valuation (SLD-стиль agrifields1.sld):
--   forest   → class 0
--   meadow   → class 3
--   tillage  → class 5
--   clearing → classes 1, 2, 4 (и всё остальное)

-- round23, задача 2: assessment_ready был обычным VIEW — пересчитывался на
-- КАЖДОЕ обращение (7.6с до фиксов round22, 2.3с после них), хотя данные
-- меняются только при доставке. Мигрируем на MATERIALIZED VIEW: данные
-- считаются один раз при доставке (CREATE — первый раз; REFRESH — каждую
-- следующую, из deliver.py, после импорта векторов и до перезагрузки
-- GeoServer), а не на каждый запрос пользователя.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_views WHERE viewname = 'assessment_ready') THEN
        DROP VIEW assessment_ready CASCADE;  -- CASCADE снимет и старый assessment_ready_latest
    END IF;
END $$;

-- assessment_ready: все годы.
-- agrifields дедуплицируется через DISTINCT ON (nr_user).
--
-- valuation / bzdz — логика:
--   Новые данные (stats IS NOT NULL): доля лес+кустарник из stats JSON.
--   Старые данные (stats IS NULL):    доля из HTML-таблицы в description (xpath).
--   Пороги valuation (совпадают с исторической логикой):
--     frac > 0.4 AND ndohod_d <= 0  → forest
--     frac > 0.3 AND ndohod_d  > 0  → clearing
--     ball_co  > 24                 → tillage
--     иначе                         → meadow
--   bzdz — категория условий хозяйствования по ndohod_d.
--
-- district — первые 4 символа nr_user (код района); нужен как обычная
-- (материализованная, индексируемая) колонка для round23, задача 1 —
-- список районов по году теперь строит deliver.py прямым SQL, не GeoServer.

CREATE MATERIALIZED VIEW IF NOT EXISTS assessment_ready AS
SELECT
    a.nr_user,
    LEFT(a.nr_user, 4)                                          AS district,
    a.geom,
    b.year,
    b.description,
    b.stats,
    b.updated_at,
    -- Площадь поля в гектарах — геодезическая (round26, B5), не из
    -- готового shape_area (исходный файл). Прежний метод (shape_area,
    -- round22) был выбран, когда пересчёт ST_Area(geom::geography)
    -- выполнялся НА КАЖДЫЙ ЗАПРОС (view, не materialized) — добавлял
    -- ~4.8с на весь набор на VPS. С round23 assessment_ready —
    -- materialized view, пересчитывается один раз за доставку через
    -- REFRESH, а не на каждый запрос — цена пересчёта геометрии больше
    -- не умножается на число запросов, и её можно платить один раз за
    -- доставку ради корректной (эллипсоидной) площади вместо площади
    -- в проекции исходного файла. Расхождение со старым методом
    -- (round26, факт на всех 59209 строках agrifields): средняя
    -- абсолютная относительная погрешность 0.0246%, максимум 51.846%
    -- (nr_user=22490000030364 — тот же дефект исходных данных, что и
    -- отмечался в round22, не новый; всего 2 строки с расхождением >10%).
    ROUND((ST_Area(a.geom::geography) / 10000)::numeric, 2)  AS area_ha,
    a.ball_co                                                  AS ball_co,
    -- Условия хозяйствования (по доходности ndohod_d)
    CASE
        WHEN a.ndohod_d > 400 THEN concat('наиболее благоприятные (', ROUND(a.ndohod_d::numeric, 1), ')')
        WHEN a.ndohod_d > 300 THEN concat('благоприятные (',          ROUND(a.ndohod_d::numeric, 1), ')')
        WHEN a.ndohod_d > 200 THEN concat('хорошие (',                ROUND(a.ndohod_d::numeric, 1), ')')
        WHEN a.ndohod_d > 100 THEN concat('удовлетворительные (',     ROUND(a.ndohod_d::numeric, 1), ')')
        WHEN a.ndohod_d > 0   THEN concat('сложные (',                ROUND(a.ndohod_d::numeric, 1), ')')
        ELSE                       concat('плохие (',                  ROUND(a.ndohod_d::numeric, 1), ')')
    END                                                        AS bzdz,
    -- Категория землепользования (через fb.frac из LATERAL)
    CASE
        WHEN fb.frac > 0.4 AND a.ndohod_d <= 0 THEN 'forest'
        WHEN fb.frac > 0.3 AND a.ndohod_d >  0 THEN 'clearing'
        WHEN a.ball_co > 24                     THEN 'tillage'
        ELSE                                         'meadow'
    END                                                        AS valuation
FROM (
    SELECT DISTINCT ON (nr_user) *
    FROM   agrifields
    ORDER  BY nr_user
) a
JOIN assessment b ON a.nr_user::bigint = b.fid_ext
-- Доля пикселей "лес+кустарник+закустаренный" (классы 0,1,2).
-- Вычисляется один раз на строку: из stats JSON (новые данные)
-- или из HTML-таблицы в description (старые данные, xpath-парсинг).
JOIN LATERAL (
    SELECT CASE
        WHEN b.stats IS NOT NULL THEN
            (
                COALESCE((b.stats::jsonb->>'0')::float, 0) +
                COALESCE((b.stats::jsonb->>'1')::float, 0) +
                COALESCE((b.stats::jsonb->>'2')::float, 0)
            ) / NULLIF(
                -- Явная сумма 6 известных классов (0=forest,1=bushes,2=bushy,
                -- 3=meadows,4=other,5=tillage) вместо jsonb_each_text-подзапроса
                -- (round22): тот вариант делал function-scan НА КАЖДУЮ строку.
                COALESCE((b.stats::jsonb->>'0')::float, 0) +
                COALESCE((b.stats::jsonb->>'1')::float, 0) +
                COALESCE((b.stats::jsonb->>'2')::float, 0) +
                COALESCE((b.stats::jsonb->>'3')::float, 0) +
                COALESCE((b.stats::jsonb->>'4')::float, 0) +
                COALESCE((b.stats::jsonb->>'5')::float, 0),
                0
            )
        WHEN b.description IS NOT NULL THEN
            (
                SELECT COALESCE(SUM((xpath('//td/text()', td))[2]::text::float), 0)
                FROM   unnest(xpath('//tr', b.description::xml)) AS td
                WHERE  xpath('//td/text()', td)::text ~* 'forest|bush'
            )
        ELSE 0
    END AS frac
) fb ON TRUE;

-- Индексы (round23, задача 2): по году, по району, по nr_user+year (уникальный
-- — держим на будущее, если понадобится REFRESH ... CONCURRENTLY), GIST по
-- геометрии — для WMS/WFS-фильтрации и пространственных запросов.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_ready_nr_user_year ON assessment_ready (nr_user, year);
CREATE INDEX IF NOT EXISTS idx_assessment_ready_year ON assessment_ready (year);
CREATE INDEX IF NOT EXISTS idx_assessment_ready_district ON assessment_ready (district);
CREATE INDEX IF NOT EXISTS idx_assessment_ready_geom ON assessment_ready USING GIST (geom);

-- assessment_ready_latest: для каждого поля — только самый свежий год.
-- Используется слоем fields_latest в GeoServer (режим "Все годы").
-- Обычный VIEW (не материализованный) — база (assessment_ready) уже
-- материализована и индексирована, DISTINCT ON по ней быстр сам по себе.
-- round27, A2 (найдено фактом при повторном прогоне на стенде):
-- `DROP MATERIALIZED VIEW IF EXISTS` падает, если объект уже
-- существует, но как обычный VIEW (штатное состояние с round26 —
-- CREATE OR REPLACE VIEW ниже как раз и делает его таким) — IF EXISTS
-- защищает только от отсутствия объекта, не от несовпадения типа.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = 'assessment_ready_latest') THEN
        DROP MATERIALIZED VIEW assessment_ready_latest;
    ELSIF EXISTS (SELECT 1 FROM pg_views WHERE viewname = 'assessment_ready_latest') THEN
        DROP VIEW assessment_ready_latest;
    END IF;
END $$;
CREATE OR REPLACE VIEW assessment_ready_latest AS
SELECT DISTINCT ON (nr_user) *
FROM   assessment_ready
ORDER  BY nr_user, year DESC;

-- levelsagg_ready (round27, A1): список землепользователей для слоя
-- pikurr:levelsagg. Раньше featuretype levelsagg читал agrifields
-- НАПРЯМУЮ (virtualTable SQL в GeoServer) — единственный слой,
-- обходивший assessment_ready, и единственный, блокировавшийся на всё
-- время транзакции подмены _stage→боевые (round26, B2: ~14.6с на VPS).
-- Материализуем тот же SELECT (семантика не менялась) и обновляем в
-- той же доставке, что и assessment_ready (deliver.py,
-- refresh_materialized_view()) — GeoServer-featuretype levelsagg
-- переключён (вручную, REST) на этот объект вместо agrifields.
CREATE MATERIALIZED VIEW IF NOT EXISTS levelsagg_ready AS
SELECT DISTINCT
    usname,
    usern_co,
    LEFT(usern_co, 4) AS rn
FROM agrifields;

CREATE UNIQUE INDEX IF NOT EXISTS idx_levelsagg_ready_all
    ON levelsagg_ready (usname, usern_co, rn);

-- round27, A2: маркер версии схемы обоих материализованных объектов —
-- см. пояснение и SCHEMA_VERSION в начале файла.
COMMENT ON MATERIALIZED VIEW assessment_ready IS 'schema_version=2';
COMMENT ON MATERIALIZED VIEW levelsagg_ready IS 'schema_version=2';
