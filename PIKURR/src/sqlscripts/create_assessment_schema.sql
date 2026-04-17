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
-- agrifields дедуплицируется через DISTINCT ON (nr_user) — в таблице бывают
-- дублирующиеся nr_user (несколько записей на одно поле), что без этого
-- порождало удвоение строк в результирующем view.
CREATE OR REPLACE VIEW assessment_ready AS
SELECT
    a.nr_user,
    a.geom,
    b.year,
    b.description,
    b.stats,
    b.updated_at,
    -- Площадь поля в гектарах
    ROUND((ST_Area(a.geom::geography) / 10000)::numeric, 2)          AS area_ha,
    -- Балл оценки: из agrifields если есть, иначе NULL
    a.ball_co::float                                                   AS ball_co,
    -- Вырубки по Hansen (не реализованы)
    NULL::float                                                        AS bzdz,
    -- Доминирующий класс → категория.
    -- Новые данные (stats IS NOT NULL): вычисляется из JSON.
    -- Старые данные (stats IS NULL): берётся сохранённое значение из assessment.valuation.
    CASE
        WHEN b.stats IS NULL THEN b.valuation
        ELSE (
            CASE (
                SELECT key
                FROM   jsonb_each_text(b.stats::jsonb)
                ORDER  BY value::float DESC
                LIMIT  1
            )
                WHEN '0' THEN 'forest'
                WHEN '3' THEN 'meadow'
                WHEN '5' THEN 'tillage'
                ELSE         'clearing'
            END
        )
    END                                                                AS valuation
FROM (
    -- Дедупликация: берём одну запись на nr_user (дубли имеют одинаковую геометрию)
    SELECT DISTINCT ON (nr_user) *
    FROM   agrifields
    ORDER  BY nr_user
) a
JOIN assessment b ON a.nr_user::bigint = b.fid_ext;

-- assessment_ready_latest: для каждого поля — только самый свежий год.
-- Используется слоем fields_latest в GeoServer (режим "Все годы").
CREATE OR REPLACE VIEW assessment_ready_latest AS
SELECT DISTINCT ON (nr_user) *
FROM   assessment_ready
ORDER  BY nr_user, year DESC;
