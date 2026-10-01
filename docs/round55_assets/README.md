# round55 — скрипты проверки (только чтение)

- `calc.py` + `valuation_compare.py` — правило `valuation` из `create_assessment_schema.sql`, применённое к `vectors.gpkg` пакетов A и B (каталоги `A/`, `B/` с извлечёнными `vectors.gpkg`); геодезическая площадь — эквивалентная по площади проекция на эллипсоиде WGS84 (отличие от `ST_Area(geography)` на контрольном поле — 1e-5 га).
- `probe_frame_order.py` — запускается через `docker exec -i pikurr-system-etl-1 python3 -c ...` (только чтение): для поля перебирает порядок листов в `calculate_zonal_stats` и сверяет результат со `stats` из A и из B. Вход (stdin) — JSON списка `{nr, geom, frames, A, B}`.
