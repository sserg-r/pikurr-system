# Входные и выходные данные системы

Раунд 51, блок B2. Форматы, системы координат, схемы таблиц, слои,
пакет обновления, служебные JSON. Источники — код (`PIKURR/`, `REPIKURR/`),
файлы исходных слоёв (`ogrinfo`, `unzip -l`), живые БД и каталоги стенда
(`192.168.251.190`, только чтение) и VPS (`geobotany.of.by`, только
чтение). Где `system-state.md` уже содержит факт — дана ссылка на его
раздел. Сокращения: `SS` = `docs/system-state.md`;
`schema.sql` = `PIKURR/src/sqlscripts/create_assessment_schema.sql`.

## 1. Входные данные ETL

### 1.1. Исходные слои (`inputs/sources/`, на стенде — `/mnt/nfsdata/PIKURR/inputs/sources/`)

| Файл | Формат | Размер | Содержимое (проверено `ogrinfo`) |
|---|---|---|---|
| `agrifields.zip` | ESRI Shapefile (`.dbf .prj .shp .shx`) в ZIP, 105 138 647 Б в распаковке | 53 886 798 Б, дата файла 2026-09-10 | 59 209 полигонов, СК — WGS 84 (геодезическая), охват (26,443; 54,894)–(30,913; 56,105) |
| `razgrafka_SK63.zip` | ESRI Shapefile (`.dbf .prj .qmd .shp .shx`) | 818 181 Б, дата содержимого 2026-01-22 | 21 280 полигонов, СК — Pulkovo 1942 / CS63 zone C2 (EPSG-эквивалент: «CS63 zone C2»; центр. меридиан 27,95°, ложный восток 2 250 000 м), охват (1 902 602; 5 641 129)–(2 604 405; 6 269 358) м |
| `agrifields_test.zip` | тот же формат | 2 476 983 Б | тестовый набор (не описан в репозитории; в git не входит) |

Модели (`inputs/models/`): `onnx/two_opset13.onnx` (47 209 600 Б) —
используется; `one/1`, `two/1` (TF SavedModel), `models.config`,
`batching_parameters.txt` — путь отката на TF Serving, кодом ETL не
читаются (`docs/deploy-etl.md`). Полный список — `hardware-software.md`, §4.

Не ETL-источники, но входы системы в целом: Sentinel-2 SCL/Cloud Score+
через Earth Engine (внешний сервис) и тайлы geodzz.by/Esri/Google (внешние
сервисы) — `etl-route.md`, шаги 2 и 4; `docs/third-party-components.md`.

### 1.2. Таблица `agrifields` (контуры участков)

Загружается `ogr2ogr` в БД с приведением к EPSG:4326 и геометрией
`MultiPolygon` (`PIKURR/src/tasks/initialize.py:68-100`). Живая таблица
ETL-БД стенда (`psql`, `information_schema`) и исходный DBF (`ogrinfo`):

| Поле | Тип (DBF → БД ETL) | Что известно в репозитории |
|---|---|---|
| `ogc_fid` | — → integer PK | служебный ключ `ogr2ogr` |
| `objectid` | Real(24.15) → numeric | не описано |
| `usname` | String(250) → varchar(250) | название/имя землепользователя — попадает в списки выбора (`levelsagg`, `REPIKURR/geoserver_data/workspaces/pikurr/postgis_pikurr/levelsagg/featuretype.xml`) |
| `num_rab` | Real → numeric | не описано |
| `ball_plpoc` | Real(25.15) → numeric | не описано |
| `ball_co` | Real(25.15) → numeric | подпись на витрине «балл КО» (`REPIKURR/repikurr/src/components/MapView.jsx:21`); порог `> 24` в правиле `valuation` (`schema.sql`, §3.3) |
| `ndohod_d` | Real(25.15) → numeric | на витрине не подписан; участвует в `valuation` (порог 0) и в `bzdz` («условия хозяйствования» — шкала 400/300/200/100/0, `schema.sql`) |
| `ddohod_d` | Real(25.15) → numeric | не описано |
| `dateco` | String(24) → varchar(24) | не описано (по имени — дата кадастровой оценки, не подтверждено) |
| `nr_user` | String(15) → varchar(15) | ключ участка «id землепользователя» (`MapView.jsx:19`); 14-значный код вида `22080000010001`; **первые 4 знака — код района** (`LEFT(nr_user,4)`, `schema.sql`), первые 2 — область (`districts_ref.json`, ключи `oblasts`) |
| `usern_co` | String(10) → varchar(10) | код землепользователя; первые 4 знака — район (`left(usern_co,4) rn`, `levelsagg`) |
| `landcode` | Real → numeric | не описано |
| `soato` | String(10) → varchar(10) | код СОАТО (по имени; не подтверждено) |
| `objectnumb`, `usern`, `num_brigad` | Real → numeric | не описано |
| `shape_leng`, `shape_area` | Real(25.15) → numeric | атрибуты исходного файла; **не используются** для площади на витрине — `area_ha` считается геодезически по геометрии (`schema.sql`, `ST_Area(geom::geography)/10000`) |
| `geom` | Polygon → geometry(MultiPolygon, 4326) | индекс GIST |

Источник исходного слоя (какая ЗИС, кто и когда выгрузил, смысл
кадастровых показателей) в репозитории не зафиксирован.

### 1.3. Таблица `razgrafka` (номенклатурная сетка 1:10 000)

| Поле | Тип | Примечание |
|---|---|---|
| `ogc_fid` | integer PK | служебный |
| `m10000_id` | Integer64(10) → numeric (ETL) / integer (`schema.sql`) | не описано |
| `n10000` | String(80) → varchar | номенклатура листа, например `N-35-10-В-а-3`; ключ листа проекта (`trapeze_serv.name`) |
| `geom` | Polygon → geometry(MultiPolygon, 4326) | СК-63 (зона C2) → EPSG:4326 при загрузке (`initialize.py:87`) |

21 280 строк; листов проекта (пересекающих `agrifields`) — 912
(таблица `trapeze_serv(name, serv)`, `serv='dzz'`).

### 1.4. Таблица `assessment` (результаты по полям и годам)

Схема на боевой БД витрины (`schema.sql:78-89`, `SS` §3):

| Поле | Тип | Примечание |
|---|---|---|
| `fid` | serial PK | |
| `id` | integer NOT NULL | значение из пакета |
| `fid_ext` | bigint NOT NULL | = `agrifields.nr_user` (приведён к bigint) |
| `year` | integer NOT NULL | год оценки |
| `stats` | varchar | JSON-строка `{"<код класса>": <доля>}`, коды 0–5, сумма долей 1; классы с нулевой долей могут отсутствовать |
| `description` | varchar | HTML-таблица «legacy»; новым кодом ETL **не заполняется** (у всех строк ETL-БД стенда `description` пуст, `psql`) |
| `updated_at` | timestamptz | |
| `valuation` | text | заполняется только для legacy-данных; для новых NULL (сценарий считается в представлении, §3) |
| ограничение | `UNIQUE (fid_ext, year)` | |

**Расхождение схем в разных контурах** (факты `psql`, 2026-09-30, не
исправлялись): в ETL-БД стенда `assessment`: `id` serial PK, `stats jsonb`,
`description text`, `updated_at timestamp without time zone`, нет `fid`;
представления `assessment_ready`/`assessment_ready_latest` — обычные VIEW,
материализованных нет; на VPS — таблица по `schema.sql` (varchar/timestamptz)
и материализованные представления (`SS` §3). Пакет несёт `stats::text`
(`package.py:71-75`), поэтому тип в ETL значения не имеет.

## 2. Промежуточные и выходные растры

Общее: GeoTIFF, uint8, один канал, EPSG:4326, сжатие LZW (кроме публичных —
COG). Координаты растра листа — граница листа `razgrafka`
(`PIKURR/src/tasks/segmentate.py:179-203`).

| Каталог | Значения пикселей | Кто пишет | Кто читает |
|---|---|---|---|
| `predictions_veget/<лист>.tif` | 0 лес, 1 кусты, 2 луг закустаренный, 3 луг чистый, 4 прочее | `segmentate` | `classify` |
| `predictions_usab/<год>/<лист>.tif` | счётчик найденных окон смены SCL (0 — нет/`nodata`), 10 м | `usability` | `classify` |
| `predictions_final/<год>/<лист>.tif` | 0–4 как выше, **5 = обработка почвы**; `nodata=255` | `classify` | `save_db`, `export` |
| `geoserver_public/<год>/<лист_латиницей>.tif` | (класс + 1) × маска полей: 1 лес … 6 обработка; **0 = фон (nodata)** | `export` | `package` → доставка → GeoServer |

Параметры COG публичных растров: `gdal_translate -of COG -co COMPRESS=LZW
-co RESAMPLING=NEAREST -co BLOCKSIZE=512` (`export.py:25-46`); передискретизация
обзоров — nearest, поскольку данные категориальные.

Расшифровка публичных значений — стиль `raster_vegetation.sld`
(`REPIKURR/geoserver_data/workspaces/pikurr/styles/raster_vegetation.sld:12-18`):
0 — белый (фон), 1 «деревья», 2 «кусты», 3 «луг закустаренный», 4 «луг чистый»,
5 «прочее», 6 «пашня».

Размеры на VPS: `data/geodata/2025` — 561 МБ, 912 файлов (`du`, `find`);
на стенде `geoserver_public/2025` — 560 МБ (`SS`, `hardware-software.md`, §5).

## 3. БД витрины: представления

### 3.1. Материализованные представления (`schema.sql`, `SCHEMA_VERSION = 3`, `SS` §3)

`assessment_ready` — все годы; строка = поле × год:

| Колонка | Источник/выражение |
|---|---|
| `nr_user` | `agrifields.nr_user` (по `DISTINCT ON (nr_user)`) |
| `district` | `LEFT(nr_user, 4)` |
| `geom` | `agrifields.geom` |
| `year`, `description`, `stats`, `updated_at` | `assessment` (`JOIN … ON nr_user::bigint = fid_ext`) |
| `area_ha` | `ROUND(ST_Area(geom::geography)/10000, 2)` |
| `ball_co` | `agrifields.ball_co` |
| `bzdz` | текст-категория по `ndohod_d` (см. `legacy-diff.md`, А2-6) |
| `valuation` | `forest` / `clearing` / `tillage` / `meadow` (`legacy-diff.md`, А2-6) |

Индексы: `UNIQUE (nr_user, year)`, `year`, `district`, GIST `geom`.
`assessment_ready_latest` — `DISTINCT ON (nr_user)` по последнему году
(`UNIQUE (nr_user)`, GIST `geom`). `levelsagg_ready` — `DISTINCT usname,
usern_co, LEFT(usern_co,4) AS rn` из `agrifields` (`UNIQUE` по трём колонкам).
Маркер версии — `COMMENT ON MATERIALIZED VIEW … IS 'schema_version=3'`.
Все три должны быть `ispopulated = t` (`CLAUDE.md`, «Текущее состояние»).

Объёмы на VPS (`pg_total_relation_size`, 2026-09-30): `agrifields` 90 МБ,
`razgrafka` 6440 кБ, `assessment` 15 МБ, `assessment_ready` 227 МБ,
`assessment_ready_latest` 220 МБ, `levelsagg_ready` 144 кБ; вся БД —
580 МБ (`docker system df`/`psql`).

### 3.2. Заглушки для чистого инстанса

`PIKURR/src/sqlscripts/bootstrap_empty_schema.sql` — пустые `assessment`,
`assessment_ready`, `assessment_ready_latest` для первого старта GeoServer
(`docs/deploy-repikurr-vps.md`, §3).

## 4. Пакет обновления (ETL → сервер витрины)

Собирается `PackageTask` (`etl-route.md`, шаг 8), имя
`pikurr_update_<годы через _>_<YYYY-MM-DD_HH-MM>.zip`
(`package.py:241`). Реальный пакет на стенде — последний по дате:
`pikurr_update_2025_2026-09-28_09-48.zip`, 537 341 400 Б (в распаковке
696 187 406 Б, 915 файлов).

Состав: `vectors.gpkg` (слои `agrifields`, `razgrafka`, `assessment`
[колонки `id, fid_ext, year, stats(text), description, updated_at`,
`package.py:71-75`]); `rasters/<год>/*.tif` (912 для 2025); 
`create_assessment_schema.sql`; `manifest.json`.

**Манифест `version: "2.1"`** (`package.py:197-228`); значения реального
пакета выше:

| Ключ | Смысл | Значение в пакете 2026-09-28_09-48 |
|---|---|---|
| `created_at` | время сборки | `2026-09-28T09:48:43` |
| `year`, `years` | последний год; все годы в пакете | 2025; [2025] |
| `version` | версия формата манифеста | 2.1 |
| `contents` | состав | `["vectors.gpkg","rasters/"]` |
| `source_db.host/name` | источник (без пароля) | `db` / `pikurr_db` |
| `etl_git_commit` | коммит кода ETL из `ETL_GIT_COMMIT` образа | `76435f18…` (40 знаков) |
| `row_counts` | число строк | agrifields 59 209; razgrafka 21 280; assessment 55 784 |
| `raster_counts_by_year` | число растров по годам | {"2025": 912} |
| `vectors_gpkg_sha256` | контрольная сумма GPKG | 64 знака |

Что сервер витрины делает с пакетом — цепочка «распаковка → проверки версии
схемы и состава лет → `pg_dump` → `_stage` → транзакция подмены → растры →
`REFRESH` → GeoServer/GWC → `year_district.json` → прогрев → `healthcheck`»
— `SS` §2, п. 5; `CLAUDE.md`, «Провенанс пакета и предполётные проверки».

**Статус-файл доставки** `status/<имя пакета>.json` (`REPIKURR/deliver.py`,
проверено на VPS): `zip`, `started_at`, `finished_at`, `ok`, `step_failed`,
`error`, `granules_after` (912), `refresh_seconds` (46,5), `healthcheck`
{`ok`,`checks[]`}, `seed_gwc_cache` {`enabled`,`layers{fields_latest,
image_assessment}`}, `manifest` (копия манифеста), `backup` {`ok`,`path`,
`size_bytes` 66 306 931,`seconds` 12,06,`retention_count` 10}; при
работе — промежуточный вид `step_in_progress`, `ok: null`. Пример — доставка
2026-09-28: начало 09:58:02, конец 10:05:19 (7 мин 17 с).

**Бэкап перед подменой**: `REPIKURR/backups/*.dump` (`pg_dump -Fc`
`agrifields`/`razgrafka`/`assessment`), ротация по числу (10); на VPS
каталог 380 МБ (`du`).

## 5. Опубликованные слои GeoServer

Рабочая область `pikurr`, пространство имён `http://pikurr`
(`REPIKURR/geoserver_data/workspaces/pikurr/namespace.xml`). Хранилище
`postgis_pikurr` (PostGIS, БД `pikurr`, схема `public`); растровое хранилище
`image_assessment` (ImageMosaic). Данные в `geoserver_data`: в git лежат
конфигурация рабочей области, стили, часть `security/**`; вне git —
`gwc`, `gwc-layers`, `logs`, `tomcat_pass.txt`, файлы паролей
(`git status --ignored`, `.gitignore`).

| Слой | Тип | Источник | СК | Кэш GWC | Назначение/стиль |
|---|---|---|---|---|---|
| `pikurr:fields` | вектор | virtual table `select * from assessment_ready`; объявлен параметр `year` со значением по умолчанию `2024` (в репозитории и на VPS одинаково), но в тексте SQL он не используется — фильтр по году задаётся клиентом через `CQL_FILTER=year=…` | EPSG:4326, MultiPolygon | нет | поля с оценкой по годам; фильтры `CQL_FILTER` (в рабочей области есть стиль `agrifields1`) |
| `pikurr:fields_latest` | вектор | `select * from assessment_ready_latest` | EPSG:4326 | **да** (`image/png`, `EPSG:900913`, метатайл 4×4, `expireCache=0`, `expireClients=86400`) | последний год, фон витрины; `Оценка полей (последний год)` |
| `pikurr:levelsagg` | вектор без геометрии | **VPS:** `select distinct usname, usern_co, left(usern_co,4) rn from levelsagg_ready`; **репозиторий (`levelsagg/featuretype.xml`):** `… from agrifields` — расхождение конфигурации репозитория и прода (на прод переключено REST, `CLAUDE.md`, round27) | EPSG:404000 (служебный) | нет | справочник землепользователей (WPS `gs:Query` в плагине) |
| `pikurr:image_assessment` | растр (ImageMosaic, `GRAY_INDEX`, `UNSIGNED_8BITS`) | `file:///mnt/data/geodata/2025/` (в репозитории и на VPS путь с годом 2025) | EPSG:4326 | **да** (как `fields_latest`) | AI-оценка текущего года (в рабочей области есть стиль `raster_vegetation`) |

Стили: `agrifields1.sld` — заливка по `valuation`: `forest #2C7D2C`,
`meadow #d9b530`, `tillage #b85c06`, `clearing #0000CC`
(`REPIKURR/geoserver_data/workspaces/pikurr/styles/agrifields1.sld:34-47`);
`raster_vegetation.sld` — 7 значений цвет/подпись (см. §2). Легенды —
`geoserver_data/legendsamples/*.png`. Квота диска GWC — 2 GiB, `LFU`, файл
`geoserver_data/gwc/geowebcache-diskquota.xml` (проверено на VPS); каталог
`gwc` — 68 МБ на VPS. Исторические растровые слои `image_assessment_<год>`
в каталоге GeoServer не заводились (`CLAUDE.md`, «Открытые вопросы»).

Подключение хранилища: пароль БД записан в `datastore.xml` — см. отчёт
раунда (блок C.2), значение в документы не переносится.

Сервисы: WMS, WFS, WPS (`gs:Query`, `vec:Aggregate`, `vec:Bounds` — шаблоны
`REPIKURR/repikurr/public/get*.xml`, `pikurr_qgis/wps_templates/*.xml`),
тайловый WMS-эндпоинт GWC `/geoserver/gwc/service/wms` (только для двух
кэшируемых слоёв, слои с префиксом `pikurr:`), WMTS GWC (плагин QGIS). Полная
таблица эндпоинтов — `SS` §4.

## 6. Служебные JSON витрины

### 6.1. `static/year_district.json`

Пишется `deliver.py:write_year_district_lookup` (`REPIKURR/deliver.py:956-1016`)
после каждой доставки, атомарно (`.tmp` → `replace`); отдаётся Caddy как
статика. Формат:

```json
{"years": [2025],
 "districtsByYear": {"2025": ["2208","2212","2218","2238","2242","2249","2258"]},
 "dataVersion": "20260928100210"}
```

Источник — `SELECT DISTINCT year, district FROM assessment_ready`. `dataVersion`
— метка последней доставки, используется фронтендом как параметр `time`
URL тайла (`CLAUDE.md`, «Ловушки», WMS `time`). Сверка с БД —
`healthcheck.py`, проверка `db_matches_static`. Для 2025 года на проде — 7
районов (2208, 2212, 2218, 2238, 2242, 2249, 2258).

### 6.2. `districts_ref.json`

`REPIKURR/repikurr/public/districts_ref.json` — справочник «код → название»:
`districts` (22 района/города, ключ — 4-значный код, значение — название) и
`oblasts` (7: 12 Брестская, 22 Витебская, 32 Гомельская, 42 Гродненская,
52 г. Минск, 62 Минская, 72 Могилёвская). Генерируется из
`REPIKURR/repikurr/src/constants.js` скриптом `REPIKURR/tools/gen_districts_ref.py`
(режим `--check` — сверка дрейфа). Читают плагин QGIS и витрина. Отдельная
серверная таблица справочника отсутствует (`gen_districts_ref.py`, шапка).
Функция `check_districts_ref` в `healthcheck.py` определена, но **в
`run_healthcheck` не вызывается** (`REPIKURR/healthcheck.py:363-386, 472-486`).
На момент round47 файл на прод не был выкачен (`docs/round47-addendum-districts-ref-not-deployed.md`);
на 2026-09-30 `curl https://geobotany.of.by/districts_ref.json` отдаёт
HTTP 200, `application/json`, 1081 Б.

### 6.3. Прочее

- `pikurr_qgis.zip` / `pikurr_qgis.sha256` / `pikurr_qgis_readme.txt` —
  архив плагина для скачивания с витрины (`REPIKURR/repikurr/public/`),
  собирается `REPIKURR/tools/build_qgis_plugin.py`; дрейф контролируется
  шагом 13b `smoke.mjs`.
- `captured_gwc_urls.json`, `tiles_with_data.json`, `all_tile_requests.json`
  — сырьё проверок (`test-methods.md`).

## 7. Что данные значат для пользователя (терминология витрины)

Подписи из интерфейса (не из ГОСТ): сценарии `forest` — «перевод в л/х»,
`tillage` — «пахотное с/х», `clearing` — «с/х после расчистки», `meadow` —
«луговое с/х» (`StatsTable.jsx:3-8`); подписи классов растительности в
карточке поля — «лес», «кустарник», «закуст. луг», «луг», «прочее»,
«пашня» (`MapView.jsx:36-37`); свойства карточки: id землепользователя,
год оценки, балл КО, Благоприятность земледелия, площадь, га, оценка
(`MapView.jsx:18-25`).
