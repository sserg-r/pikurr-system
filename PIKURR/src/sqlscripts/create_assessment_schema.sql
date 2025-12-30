-- 1. Таблица результатов оценки
CREATE TABLE IF NOT EXISTS assessment (
    id SERIAL PRIMARY KEY,
    fid_ext BIGINT NOT NULL,       -- ID пользователя/поля из agrifields
    year INTEGER NOT NULL,         -- Год оценки
    stats JSONB,                   -- Статистика в JSON (современно)
    description TEXT,              -- HTML таблица (для старых клиентов/GeoServer)
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Важно для ON CONFLICT в скрипте сохранения:
    CONSTRAINT assessment_fid_year_key UNIQUE (fid_ext, year)
);

-- Индекс для скорости поиска
CREATE INDEX IF NOT EXISTS idx_assessment_fid_year ON assessment (fid_ext, year);

-- 2. Представление (View) для публикации
-- Соединяет геометрию полей с результатами оценки.
-- Именно этот слой нужно публиковать в GeoServer.
DROP VIEW IF EXISTS assessment_ready;

CREATE OR REPLACE VIEW assessment_ready AS
SELECT 
    a.nr_user,
    a.geom,
    b.year,
    b.description,
    b.stats,
    b.updated_at
FROM agrifields a
JOIN assessment b ON a.nr_user::bigint = b.fid_ext;