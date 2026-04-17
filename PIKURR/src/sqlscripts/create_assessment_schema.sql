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

DROP VIEW IF EXISTS assessment_ready_latest;
DROP VIEW IF EXISTS assessment_ready;

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

CREATE OR REPLACE VIEW assessment_ready AS
SELECT
    a.nr_user,
    a.geom,
    b.year,
    b.description,
    b.stats,
    b.updated_at,
    -- Площадь поля в гектарах
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
                (SELECT SUM(t.val::float) FROM jsonb_each_text(b.stats::jsonb) AS t(k, val)),
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

-- assessment_ready_latest: для каждого поля — только самый свежий год.
-- Используется слоем fields_latest в GeoServer (режим "Все годы").
CREATE OR REPLACE VIEW assessment_ready_latest AS
SELECT DISTINCT ON (nr_user) *
FROM   assessment_ready
ORDER  BY nr_user, year DESC;
