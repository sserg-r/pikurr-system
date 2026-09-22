# Раунд 30: цена `fields_latest`, ошибки Caddy, опрос статуса, повторный замер

См. `prompts/PROMPT_latest_view_round30.md`. Главная гипотеза (проверить
первой, до правок): регрессия round29 вызвана не COG и не
`controlflow`, а тем, что после правки C.1 весь векторный трафик идёт
в `assessment_ready_latest` — обычный `VIEW` с `DISTINCT ON` поверх
`assessment_ready`, пространственный фильтр не проталкивается внутрь
`DISTINCT ON`.

---

## Блок A. Проверка гипотезы — подтверждена

### A.1. Реальный SQL (машина: VPS, `pikurr_vps_postgis`)

`log_min_duration_statement=0` включён на время замера
(`ALTER SYSTEM` + `pg_reload_conf()`), возвращён обратно сразу после
(`-1`, подтверждено `SHOW`). Реальные запросы одного тайла каждого
слоя (`curl` на `https://geobotany.of.by`, те же параметры, что
реально шлёт фронтенд) захвачены из журнала PostgreSQL (напрямую из
файла `.../*-json.log` — `docker logs --since` на этой машине не
показывал недавние строки надёжно, разбирался отдельно, не связано с
самой гипотезой).

**`fields_latest`**:
```sql
SELECT "valuation",encode(ST_AsTWKB(ST_Simplify(ST_Force2D("geom"), 0.0012482721068124648, true),3), 'base64') as "geom"
FROM (select * from assessment_ready_latest) as "vtable"
WHERE "geom" && ST_GeomFromText('POLYGON (...)', 4326)
```

**`fields`** (`CQL_FILTER=year=2025`):
```sql
SELECT "valuation",encode(ST_AsTWKB(ST_Simplify(ST_Force2D("geom"), 0.0012482721068124648, true),3), 'base64') as "geom"
FROM (select * from assessment_ready) as "vtable"
WHERE ("year" = 2025 AND "year" IS NOT NULL AND "geom" && ST_GeomFromText('POLYGON (...)', 4326))
```

Разница уже видна по тексту: у `fields_latest` фильтр `geom &&` навешан
**поверх** `select * from assessment_ready_latest` (сама `DISTINCT ON`
дедупликация — внутри представления, до этого фильтра); у `fields`
фильтр по году и по геометрии — оба в одном `WHERE`, к материализованной
таблице напрямую.

### A.2. `EXPLAIN (ANALYZE, BUFFERS)` — 5 прогонов каждого, порядок
перемешан (seed=2032: `fields, fields, latest, latest, fields, latest,
fields, latest, fields, latest`)

**`fields_latest`** (все 5 прогонов, план идентичен по структуре):
```
Subquery Scan on assessment_ready_latest  (actual time=185-249..234-292 rows=4603)
  Filter: geom && ...
  Rows Removed by Filter: 51181
  ->  Unique  (actual time=99-158..200-255 rows=55784)
        ->  Parallel Seq Scan on assessment_ready  (actual time=0.02..22-25 rows≈18595×3 loops)
Execution Time: 236.6 / 239.8 / 251.3 / 275.9 / 292.5 мс
```

**`fields`** (все 5 прогонов):
```
->  Bitmap Index Scan on idx_assessment_ready_geom  (actual time≈0.47-0.51 rows=4603)
Execution Time: 20.9 / 20.9 / 21.1 / 21.2 / 21.6 мс
```

**Подтверждено фактом, не предположением**: `fields_latest` выполняет
`Unique` (дедупликация `DISTINCT ON`) над **всеми 55784 строками**
`assessment_ready` — `Rows Removed by Filter: 51181` из 55784 означает,
что пространственный фильтр отбрасывает 91.7% строк **после**, а не
**до** дорогой сортировки/дедупликации. `fields` использует
`idx_assessment_ready_geom` (GIST) напрямую и не трогает лишние
строки вообще. **`fields_latest` в среднем в ~11-14× медленнее**
(236-293мс против 21мс) на идентичном запросе к одному тайлу.

### A.3. Время одного тайла через публичный домен (`curl`, 5 прогонов
каждого, машина: с координатора на VPS через интернет — включает TLS/
сеть/рендер, не только SQL)

| run | `fields_latest` | `fields` |
|---|---|---|
| 1 | 0.986с | 0.783с |
| 2 | 0.914с | 0.654с |
| 3 | 0.969с | 0.709с |
| 4 | 0.882с | 0.706с |
| 5 | 1.008с | 0.606с |

Разница (~250-300мс на тайл) сохраняется и на полном HTTP-пути,
согласуется с разницей в SQL (сеть/TLS/рендер — общий для обоих слоёв
компонент, добавляющийся сверху одинаково).

### A.4. Соответствие профиля round28 реальному поведению фронтенда

Скрипт round28 (`/tmp/round28_k6/realistic_profile.js`, VPS-блок B)
запрашивал `pikurr:fields_latest` **и** на `page_load` (24 тайла), **и**
повторно на каждом `zoom_change` (строка 177) — то есть уже тогда
периодически трогал медленный слой, не только на первой загрузке.
`pan` — только `pikurr:fields` (строка 207, с явным комментарием "по
перехвату A3... fields_latest уже был в кэше").

**Реальный фронтенд до round29** (когда `selectedYear` автоматически
устанавливался в конкретный год сразу после монтирования, round28 A3):
слой `fields_latest` использовался **только на долю секунды** при
самой первой загрузке — тут же происходил переход на `fields` (быстрый,
индексированный), и **весь остальной сеанс пользователя** (все панорамирования
и зумы) шёл через `fields`.

**Реальный фронтенд после round29, блок C.1**: `selectedYear` больше
**никогда** не устанавливается автоматически — `vectorLayer` остаётся
`'pikurr:fields_latest'` **на всю сессию**, пока пользователь сам не
откроет боковую панель и не выберет конкретный год. Это означает, что
устранение "гонки" (правка C.1, сама по себе корректная и доказанная
для своей узкой цели — не дублировать 12 тайлов на первой загрузке)
**побочно перевело весь сеанс пользователя на медленный путь**, а не
только первую загрузку страницы. Round28's тест частично касался
`fields_latest` на зумах и не был чист от этого эффекта даже раньше,
но не то же самое, что «весь сеанс на медленном пути» — этим и
объясняется, почему round28 не увидел проблему в том масштабе, в
котором её увидел round29.

**Вывод**: гипотеза раунда **подтверждена фактом** — регрессия round29
вызвана именно ценой `fields_latest` (`DISTINCT ON` без индексируемого
пути), усугублённой тем, что правка C.1 того же раунда 29 сделала этот
дорогой слой единственным для всей сессии пользователя, а не только
для первой загрузки. Блок B выполняется.

---

## Блок B. `assessment_ready_latest` — материализовано

### B.1-B.2. Правки

`PIKURR/src/sqlscripts/create_assessment_schema.sql`:
`assessment_ready_latest` — теперь `CREATE MATERIALIZED VIEW IF NOT
EXISTS` (тот же `SELECT DISTINCT ON (nr_user) * FROM assessment_ready
ORDER BY nr_user, year DESC`, семантика не менялась), плюс
`GIST`-индекс по `geom` (единственный реальный фильтр — блок A.1) и
уникальный индекс по `nr_user`. `SCHEMA_VERSION = 3`, маркер
`schema_version=3` на всех трёх материализованных объектах.

`REPIKURR/deliver.py`: `SCHEMA_VERSION = 3`,
`_VERSIONED_MATERIALIZED_VIEWS` теперь включает
`assessment_ready_latest`; `refresh_materialized_view()` обновляет его
явно, **после** `assessment_ready` (зависимость — `SELECT DISTINCT ON`
поверх него, `REFRESH` не каскадируется автоматически).

**Найден и исправлен реальный баг по ходу проверки** (не в задачах
ТЗ, но заблокировал бы каждый следующий апгрейд версии схемы): миграция
v2→v3 первой же попыткой упала — `ensure_assessment_schema()`
безусловно выполняла `DROP VIEW IF EXISTS {view} CASCADE` **и**
`DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE` для каждого объекта
из списка (правка round28, придуманная для случая "объект уже
MATERIALIZED VIEW, ожидался VIEW"). Оказалось, что `IF EXISTS`
защищает только от отсутствия ИМЕНИ, но не от несовпадения ТИПА в
обе стороны: `DROP VIEW IF EXISTS x`, когда `x` уже `MATERIALIZED
VIEW`, тоже падает (`"assessment_ready" is not a view`). Это
единственный по-настоящему первый случай, когда в проде выполнялась
миграция версии схемы для объекта, УЖЕ материализованного заранее
(round28/29 либо создавали объекты с нуля, либо не поднимали
`SCHEMA_VERSION`) — баг был в коде с round28, но ни разу не
срабатывал. Исправлено: перед `DROP` определяется фактический
`relkind` объекта (`_relkind()`, уже был в коде) — дропается только
подходящей командой.

### B.3. Проверка на эмуляторе

1. **Миграция v2→v3**: эмулятор был на `schema_version=2`
   (`assessment_ready_latest` — обычный `VIEW`, без версии).
   Собран тестовый пакет с новым `create_assessment_schema.sql`
   (`SCHEMA_VERSION=3`) поверх реальных данных, доставлен —
   **успешно** (после фикса выше), `healthcheck` зелёный.
   Фактически после доставки: все три объекта —
   `relkind='m'` (materialized), `obj_description = 'schema_version=3'`.
2. **Повторная доставка тем же (v3) пакетом** — `ok: true`,
   `healthcheck` зелёный, **OID не изменились**
   (`assessment_ready=127429`, `assessment_ready_latest=138151`,
   `levelsagg_ready=148879` — до и после повторной доставки идентичны).
3. **Пакет со старой схемой (`SCHEMA_VERSION=2`) после того, как БД
   уже на v3** — **отказ** на шаге `check_schema_version`
   (`SchemaVersionError: Пакет несёт SCHEMA_VERSION=2, боевая схема
   уже на SCHEMA_VERSION=3...`), OID объектов **не изменились**
   (проверено после попытки) — ничего не тронуто, как и задумано в
   round29, блок A.4.

### B.4. Эквивалентность содержимого

Сравнение материализованного результата с прямым, честным пересчётом
того же `SELECT DISTINCT ON` (эмулятор, реальные данные — 59209 строк
`agrifields`, 55784 уникальных `nr_user` в `assessment_ready`):

| | count |
|---|---|
| `assessment_ready_latest` (материализовано) | 55784 |
| Прямой `SELECT DISTINCT ON (nr_user) ...` | 55784 |
| Расхождений в множестве `(nr_user, year)` (`EXCEPT`) | **0** |

**Подтверждено** полностью — содержимое идентично, число объектов и
множество `(nr_user, year)` совпадают.

### B.5. Развёртывание на VPS — 3 доставки

Стенд обновлён до `origin/main` (незакоммиченный локальный дифф
`export.py` оказался идентичен origin — отброшен, как и в round29),
образ ETL пересобран. `deliver.py` на VPS обновлён с бэкапом
(`deliver.py.bak_pre_round30`).

**3 реальные доставки на VPS** (`geobotany.of.by`, канал
стенд→VPS — `rsync` через реальный delivery-канал, подхват
вотчдогом):

| # | Передача | `deliver.py` (started→finished) | `refresh_seconds` | Итог |
|---|---|---|---|---|
| 1 | 56.3с | 18:11:47→18:15:32 | **35.42с** (миграция v2→v3) | `ok:true`, healthcheck зелёный, 912 гранул |
| 2 | 47.3с | 18:17:46→18:21:00 | **27.72с** | `ok:true`, healthcheck зелёный, 912 гранул |
| 3 | 47.3с | 18:23:02→18:27:16 | **34.73с** | `ok:true`, healthcheck зелёный, 912 гранул |

Первая доставка выполнила реальную миграцию v2→v3 на боевой VPS
(`REFRESH` трёх материализованных представлений + пересборка
`assessment_ready`/`assessment_ready_latest`, отсюда самый долгий
`refresh_seconds` не выделяется явно — общий шаг). Подтверждено
фактом: все три объекта на VPS — `relkind='m'`,
`obj_description='schema_version=3'`.

**Откат** (при необходимости):
```
ssh 158.160.237.90 "cp ~/repikurr/deliver.py.bak_pre_round30 ~/repikurr/deliver.py"
# и доставить пакет со старым SQL (SCHEMA_VERSION=2) — deliver.py
# после отката снова примет его как соответствующий своей версии.
```

### B.6. Повтор A.2/A.3 на VPS после правки

**`EXPLAIN (ANALYZE, BUFFERS)`, 5+5 прогонов, перемешанный порядок**
(seed=2033: `latest, fields, fields, fields, fields, latest, latest,
latest, latest, fields`):

| Слой | План | Execution Time (5 прогонов) |
|---|---|---|
| `fields_latest` | `Bitmap Index Scan on idx_assessment_ready_latest_geom` (новый индекс) | 21.28 / 21.32 / 21.57 / 22.50 / 22.47 мс |
| `fields` | `Bitmap Index Scan on idx_assessment_ready_geom` | 21.15 / 22.20 / 29.03 / 31.04 / 21.14 мс |

**`Unique` полностью исчез из плана** — `fields_latest` теперь
использует свой собственный `GIST`-индекс напрямую, время выполнения
практически неотличимо от `fields` (в пределах обычного разброса
между прогонами одного и того же запроса, не системная разница).

**Время одного тайла через публичный домен** (`curl`, 5 прогонов
каждого):

| run | `fields_latest` (после) | `fields` |
|---|---|---|
| 1 | 0.807с | 0.809с |
| 2 | 0.632с | 0.688с |
| 3 | 0.679с | 0.733с |
| 4 | 0.629с | 0.730с |
| 5 | 0.769с | 0.715с |

**Подтверждено фактом на реальном VPS**: разница между слоями,
установленная в блоке A (~11-14× по SQL, ~250-300мс на тайл по HTTP),
**полностью устранена**. Блок B выполнен целиком.

---
