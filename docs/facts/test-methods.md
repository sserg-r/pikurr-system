# Сырьё для программы и методики испытаний

Раунд 51, блок B6. Все автоматические проверки, что и по какому критерию
они проверяют, как запускаются, где нужен доступ; отдельно — функции ETL,
**не** покрытые ни одним автоматическим тестом (пробелы будущей ПМИ; в
раунде 51 **не закрывались**). Источник — чтение кода проверок; ни одна
проверка в раунде 51 **не запускалась** против прода/стенда (правило
раунда: только чтение), поэтому «результат последнего прогона» здесь не
приведён; последние зафиксированные прогоны — в отчётах раундов (ссылки).

Сокращения: `HC` = `REPIKURR/healthcheck.py`; `SMK` =
`REPIKURR/tools/smoke/smoke.mjs`; `E2E` =
`pikurr_qgis/tests/test_plugin_e2e.py`; `HL` =
`pikurr_qgis/tests/test_headless.py`.

## 1. Автоматические проверки контура витрины

### 1.1. `REPIKURR/healthcheck.py`

- **Запуск**: `python3 REPIKURR/healthcheck.py --base-url https://geobotany.of.by [--json]`
  (`HC:488-509`); по умолчанию `--base-url` = `HEALTHCHECK_BASE_URL` или
  `https://$DOMAIN` (иначе `geobotany.of.by`). Код возврата 0 — все проверки
  зелёные, 1 — есть несоответствие. Вызывается также **в конце
  `deliver.py`** (результат — в статус-файле доставки, ключ `healthcheck`,
  `REPIKURR/deliver.py:1695`), и `external_healthcheck.sh` (каждые 5 мин со стенда).
- **Доступ**: публичный HTTPS витрины — для всех проверок, кроме двух
  локальных: `db_matches_static` (клиент `psql`, переменные
  `FRONTEND_DB_HOST/PORT/USER/NAME`, обязательно `FRONTEND_DB_PASSWORD`,
  `HC:47-55,398-440`) и `disk_space` (локальный диск, `DISK_CHECK_PATH`,
  `DISK_FREE_MIN_GB`, по умолчанию 3, `HC:443-469`). Для `gwc_layer[…]`,
  `filtered_layer` нужны файлы `TILES_WITH_DATA_PATH`
  (`docs/round32_assets/tiles_with_data.json`) и `CAPTURED_GWC_URLS_PATH`
  (`REPIKURR/tools/smoke/captured_gwc_urls.json`, пишется `smoke.mjs`); без них
  проверки красные по независящей от кода причине (`CLAUDE.md`).
- **Проверки** (порядок — `HC:472-486`), критерии — **по содержимому**, не по
  коду ответа:

| Проверка | Запрос | Критерий «зелёная» | Код |
|---|---|---|---|
| `wms_getmap` | `/geoserver/pikurr/wms` GetMap `pikurr:image_assessment`, bbox `26,54,27,55` | в теле нет `ServiceExceptionReport`; PNG (сигнатура) и размер ≥ 200 Б | `HC:76-97`, `62-73` |
| `gwc_layer[<слой>]` (для каждого слоя из `captured_gwc_urls.json`: сейчас `pikurr:fields_latest`, `pikurr:image_assessment`) | тот же URL, что шлёт фронтенд (`/geoserver/gwc/service/wms`), `bbox` заменён на заведомо непустой тайл | нет «Unknown layer»/«GWC Error»; PNG ≥ 200 Б; в детали пишется `geowebcache-cache-result` (HIT/MISS — **не критерий**) | `HC:136-198` |
| `filtered_layer` | `/geoserver/pikurr/wms`, `fields_latest`, `CQL_FILTER=nr_user LIKE '<район 2208>%'` (`FILTERED_LAYER_DISTRICT`) | нет `ServiceExceptionReport`; PNG ≥ 200 Б | `HC:201-244` |
| `wfs_getfeature` | `/geoserver/pikurr/ows` WFS 1.0.0 `pikurr:fields`, 5 объектов, JSON | не `ServiceExceptionReport`; JSON; `features` непуст; атрибуты не все пустые | `HC:247-288` |
| `error_path` | `/geoserver/nonexistent` | код **не** 200 и тело непустое (защита от синтетического 200 Caddy) | `HC:291-322` |
| `main_page` | `/` | HTTP 200 и в теле `<div id="root"` | `HC:324-333` |
| `year_district_json` | `/static/year_district.json` | JSON, непустой `years`; пишется число пар год/район | `HC:336-360` |
| `db_matches_static` | `SELECT DISTINCT year, district FROM assessment_ready` через `psql` | множество пар в БД == множество пар в `year_district.json` | `HC:398-440` |
| `disk_space` | локально | свободно ≥ порога (3 ГБ) | `HC:443-469` |

  Итого **10 записей** в вердикте при двух слоях (`gwc_layer[…]` × 2); при
  отсутствии `captured_gwc_urls.json` вместо них — одна красная запись
  `gwc_layers` (`HC:146-166`). Зафиксированный результат при доставке
  2026-09-28: `healthcheck.ok: true`, 10/10 (`SS` §6; статус-файл на VPS).
- **Наблюдения по самой проверке** (не исправлялось):
  - Критерий «непустого» PNG слабый: сигнатура + длина ≥ 200 Б (`HC:62-73`);
    заголовок функции обещает «непустой чанк IDAT», но код IDAT не
    проверяет — PNG ≥ 200 Б с прозрачными пикселями пройдёт. Более строгая
    проверка (порог 2048 Б) — в `REPIKURR/tools/verify_tiles_have_data.py`.
  - Функция `check_districts_ref` определена (`HC:363-386`), но в
    `run_healthcheck` **не вызывается** — доступность `districts_ref.json` не
    контролируется.
  - `wfs_getfeature` не проверяет год и не сверяет число объектов.

### 1.2. `REPIKURR/tools/smoke/smoke.mjs` (браузерный дымовой сценарий)

- **Запуск**: `cd REPIKURR/tools/smoke && npm install && npx playwright
  install chromium && BASE_URL=https://geobotany.of.by node smoke.mjs`
  (`CLAUDE.md`, «Инструменты измерения»; зависимость `playwright ^1.48`,
  фактически 1.63.0 по `TPC`). Переменные: `BASE_URL`, `HEADLESS`
  (`false` — с окном), `CAPTURE_OUT`. Node 22. Код возврата: 0 — все шаги
  PASS; 1 — есть FAIL; 2 — исключение сценария (`SMK:583-595`).
- **Доступ**: публичный HTTPS витрины; исходящий доступ браузера к
  Интернету (внешние подложки OSM/Esri); на координаторской машине —
  только сам Chromium без `--with-deps` (нет sudo, `CLAUDE.md`).
- **Побочные результаты**: `captured_gwc_urls.json`, `all_tile_requests.json`
  (`SMK:563-581`) — вход для `healthcheck.py` и `analyze_zoom_usage.py`.
- **Шаги** (в текущем коде — 23 именованных проверки; критерий — по
  содержимому: DOM/сеть/консоль браузера; кэш браузера отключён через CDP,
  `SMK:41-51`):

| Шаг | Что проверяется | Критерий |
|---|---|---|
| 1 | загрузка страницы | заголовок `h2` = «ПИК УРР», панель видна (`SMK:116-124`) |
| 2 | выбор года | ошибок консоли нет; при единственном годе — пропуск как PASS |
| 2b | год в теле WPS-запроса статистики | `typeName="pikurr:fields"` и условие `year` (только если есть 2-й год, иначе пропуск как PASS) |
| 3 | выбор района | нет ошибок консоли |
| 3.1–3.3 | подсветка: область / район / землепользователь | есть запросы верхнего слоя с `CQL_FILTER` через `/geoserver/pikurr/wms`; в GWC-запросах `CQL_FILTER` = 0 (ожидание 5000 мс между действиями — фиксированное, «теоретически хрупко», `CLAUDE.md`) |
| 3.4 | сброс группы | запросов с `CQL_FILTER` после сброса нет; ошибок консоли нет |
| 4a, 4b | слой «AI оценка» вкл/выкл | GWC-запросы все 200; после выключения тайлов `image_assessment` в DOM нет |
| 5 | клик по полю | карточка «Детали участка» с таблицей/свойствами/описанием |
| 6, 7 | зум, сдвиг | нет ошибок консоли |
| 8 | клик в углу без данных | карточка не появилась, ошибок нет |
| 9 | переключатель подложки | разные хосты тайлов у OSM и Esri; «Нет» — без тайлов подложки |
| 10a, 10b | чекбокс «С/х участки» | переключение и возврат к исходному |
| 11, 11b | «О системе» | модалка видна, текст > 20 символов; закрывается |
| 12a, 12b | сворачивание панели | `.sidebar.collapsed`, кнопка открытия видна; развёртывание |
| 13 | файлы плагина | `/pikurr_qgis.zip` и `/pikurr_qgis_readme.txt`: 200, не `text/html`, размер > 0 |
| 13b | дрейф архива плагина | sha256 тела `/pikurr_qgis.zip` == значению из `/pikurr_qgis.sha256` |

  Зафиксированные прогоны: 13/13 на прод в round44 (более ранняя редакция
  сценария, `CLAUDE.md`); 21/22 в round47 (единственный красный — 13b до
  выкладки нового архива, `docs/round47-addendum-districts-ref-not-deployed.md`).
  В `CLAUDE.md` число «13» относится к прежней редакции; в текущем
  сценарии — 23 проверки (подсчёт по именам шагов).
- **Проверки эталонных чисел (1 объект / 5,6 га; 9039 / 84 732 га) в
  сценарии нет.**

### 1.3. Разовые диагностические сценарии (не постоянные тесты)

- `REPIKURR/tools/smoke/round50_year_check.mjs` — локально собранная
  витрина против прода с подменённым `year_district.json` (два года), чтобы
  проверить сценарий смены года (по шапке файла).
- `REPIKURR/tools/smoke/round50_bbox_null_check.mjs` — прямой вызов
  `getBboxByUser()` для года без данных: различает пустой и непустой
  результат (по шапке файла).
- `REPIKURR/tools/smoke/measure_batch_sizes.mjs` — подсчёт размера пачки
  тайловых запросов по типу действия.

### 1.4. Проверки дрейфа и целостности конфигурации

| Проверка | Что сверяет | Запуск | Доступ |
|---|---|---|---|
| `smoke.mjs` 13b | sha256 опубликованного архива плагина против `pikurr_qgis.sha256` | как `smoke.mjs` | HTTPS |
| `REPIKURR/tools/build_qgis_plugin.py --check` | что `public/pikurr_qgis.zip` соответствует сборке из `pikurr_qgis/` | `python3 REPIKURR/tools/build_qgis_plugin.py --check` | локально; вызывается `deploy_frontend_vps.sh` |
| `REPIKURR/tools/gen_districts_ref.py --check` | `public/districts_ref.json` против `constants.js` | `python3 REPIKURR/tools/gen_districts_ref.py --check` | локально; вызывается `deploy_frontend_vps.sh` |
| `REPIKURR/deploy_backend_vps.sh --check` | sha256 `deliver.py`, `healthcheck.py`, `watchdog.py` и вспомогательных файлов на VPS против репозитория | `REPIKURR/deploy_backend_vps.sh --check` (`VPS_HOST` параметризован) | SSH к VPS |
| `REPIKURR/tools/tile_math.py --self-check` | математика lon/lat↔тайл против `docs/round32_assets/tiles_with_data.json` (20 записей) | `python3 REPIKURR/tools/tile_math.py --self-check` | локально |
| Внутри `deliver.py`: предохранители | версия схемы (`SwapGuardError`), состав лет (`YearCompositionGuardError`), усадка (`SwapGuardError`), `pg_dump` до подмены; сверка засева GWC с геометрическим расчётом (`shortfall_warning`) | часть каждой доставки; обход — `--allow-year-change`, `--allow-shrink` | на сервере доставки |
| Внутри `package.py`: `check_missing_sheets` | TIF года против `trapeze_serv` (только `ERROR` в лог) | часть сборки пакета | ETL |

  Перечисленное — **предохранители и проверки конфигурации**, а не
  автоматические тесты в смысле юнит-/интеграционных; результат каждой
  фиксируется в логе/статусе, а не в отчёте прогона тестов. Отдельного
  тестового набора для `deliver.py` и `watchdog.py` в репозитории **нет**
  (обкатка предохранителей — ручные эксперименты, `docs/round39-cleanup.md`,
  блоки B, C).

### 1.5. Инструменты замеров (не проверки соответствия)

`REPIKURR/tools/k6_loadtest.js`, `capacity_k6.js` (нагрузка; k6 2.3.0,
`TPC`), `verify_tiles_have_data.py` (`--base-url`, `--layer`, `--via gwc|wms`,
`--tiles`, `--z`, `--min-bytes` 2048 — доля пустых тайлов, предупреждение
выше 20 %), `gwc_http_seed.py`, `analyze_zoom_usage.py`,
`mincore_residency.py`, `gwc_metatile_experiment.py` (**только эмулятор**),
`check_delivery_window.sh`. Правила замеров — `CLAUDE.md`, «Правила замеров».

## 2. Автоматические проверки плагина QGIS

Общие условия (`HL`/`E2E`, шапки файлов): QGIS 3.44 на машине запуска;
плагин установлен в профиль QGIS (`~/.local/share/QGIS/QGIS3/profiles/default/
python/plugins/pikurr_qgis/`) и синхронизирован с `pikurr_qgis/`; запуск —
`qgis --code <скрипт>` с `QT_QPA_PLATFORM=offscreen`, из чистого окружения
(`env -u VIRTUAL_ENV -u PYTHONPATH -u http_proxy -u https_proxy PATH=…`);
**доступ к боевому серверу `https://geobotany.of.by`** (без моков);
`__file__` в `qgis --code` не определён; любое необработанное исключение
блокирует процесс без вывода (`CLAUDE.md`, «Ловушки», round47/48);
вывод — `print(..., flush=True)`, код `os._exit()`.

### 2.1. `pikurr_qgis/tests/test_headless.py`

Печатает `HEADLESS: N/M PASS`; 6 шагов без GUI-событий (сеть, разбор,
списки, добавление слоёв, запрос статистики):

1. сервер доступен по содержимому (WPS `GetCapabilities`);
2. справочник районов с сервера;
3. WPS `gs:Query` (`levelsagg` → список районов);
4. эталонный землепользователь `2212000055` найден в списке района 2212;
5. статистика по эталону = 1 объект, 5,6 га, `tillage`;
6. независимая сверка прямым WFS (не через код плагина).

Источник эталона — round46, блок A.4 (шапка файла).

### 2.2. `pikurr_qgis/tests/test_plugin_e2e.py`

Проверка через реальный `iface` и реальные Qt-события (`QTest`, сырые
`QKeyEvent` для кириллицы). Шаги (по коду): 0 — панель создана как
`QDockWidget`; A2 — навигация стрелками по `districtCombo`/`userCombo`
вызывает `activated` и меняет таблицу, программное `setCurrentIndex` — нет;
A1 — числа плагина == числа запроса витрины (`getstatsbyuser.xml` при том же
CQL); A4 — центр объекта и центр района 2212 внутри охвата карты; A5 —
слой полей содержит `transparent=true` и на охвате одного участка в
основном прозрачен; A6 — CRS проекта не меняется при включении AI-оценки;
B2 — год без данных (2024): таблица пуста, карта не сдвинута; A3 — поиск
по подстроке и по коду, несуществующий текст не добавляет пункт; 4a/4b —
группа «ПИК УРР», повторные выборы не плодят слои; 5 — AI-оценка (WMTS)
отрисована, доля непрозрачных пикселей > 0; 6a/6b/6c — недоступный адрес,
адрес не-GeoServer, мусорный ответ: панель жива. Последний
зафиксированный результат — 20/20 (`docs/round50-autonomous.md:81`).

Файлы `measure_speed.py`, `measure_speed_after.py` — замер скорости
операций плагина, не проверки соответствия.

## 3. Тесты ETL

### 3.1. Что есть

Файлы `PIKURR/test_*.py` и `PIKURR/dedug_inference.py` лежат **только на
координаторской машине**: они не отслеживаются git (`git ls-files` не
выдаёт ни одного; `.gitignore` их не допускает), и `PIKURR/.dockerignore`
исключает `test_*.py`, `debug_*.py` из образа — **вопреки строке в
docstring** («`docker compose run --rm etl python test_round5_download.py`»,
`PIKURR/test_round5_download.py:6-9`, `test_round6_progress.py:5-7`): в
образ эти файлы по умолчанию не попадают; как их предполагалось запускать
без монтирования, не документировано и в раунде 51 не проверялось.

| Файл | Что | Форма |
|---|---|---|
| `test_round5_download.py` | 9 проверок на моках (без сети): предохранитель `exportImage` срабатывает/игнорирует повтор координаты/сбрасывается; проба отключает фазу A; маркер блока предотвращает повторный запрос и не создаётся при исключении; отдых по времени и его разброс; лимит сессии | самопроверка: `check()`, при провале `SystemExit(1)` |
| `test_round6_progress.py` | 6 проверок `ProgressReporter` (ограничение частоты вывода по времени, исключение пропущенных из скорости, скользящее окно, предупреждение о лимите сессии, отключение, итоговая сводка) на подменённых часах | самопроверка |
| `test_download_safe.py`, `test_usability.py`, `test_classify.py`, `test_save_db.py`, `test_segmentation.py`, `test_gee_auth.py`, `test_config_load.py` | ручные скрипты: подмена списка листов/`bbox` на синтетические (например `TEST_USABILITY_FIELD`, район Минска), запуск задачи, печать; **ни одного `assert`/`check`** (`grep`); `test_usability.py`/`test_gee_auth.py` обращаются к Google Earth Engine, `test_download_safe.py` — к реальным источникам тайлов; `test_segmentation.py` импортирует устаревший `segmentate_old` | ручной осмотр вывода |
| `dedug_inference.py` | проверка соединения с TF Serving по gRPC (`ovmsclient`) | устарела (TF Serving отключён) |

Автоматических тестов **в репозитории** для ETL — нет. Эквивалентность ONNX
и TF Serving проверялась однократно вручную и описана в
`docs/deploy-etl.md` («Инференс: ONNX Runtime»).

### 3.2. Функции ETL, не покрытые ни одним автоматическим тестом

«Автоматический тест» = проверка с критерием и кодом возврата, лежащая в
репозитории. Перечень — пробелы будущей ПМИ; **не закрывались**.

| Модуль | Не покрыто |
|---|---|
| `src/tasks/initialize.py` | загрузка `ogr2ogr` (СК, `-select`, `PROMOTE_TO_MULTI`), построение `trapeze_serv`, создание схемы |
| `src/tasks/download.py` | `passes_quality` (порог 0,7), порядок и переходы водопада источников (`process_tile`), `process_block` (качество, пул, ссылки), `_check_completeness` / `_missing.json`, `calculate_tile_ranges`, `_load_affected_sheets` / режим `esri_only`, `_decode`, `_fetch_*`. (Покрыты только: предохранитель, проба, маркер блока, отдых, лимит сессии — round5) |
| `src/services/dzz_export.py` | `fetch_block`, `fetch_tile_via_export`, `slice_block`, разбор ответа и распознавание отказа каталога |
| `src/utils/http_retry.py` | политика ответов 401/403/404/429/503/5xx и повторов |
| `src/utils/image.py` | `split_image`, `merge_imageset`, `merge_tiles` (в т. ч. недостающие тайлы и `<лист>_gaps.json`) |
| `src/utils/geo.py` | `getTileIndex`, `get_tile_range_for_bbox`, `tileZXYToLatLonBBox`, `get_bbox_for_tileset(_mercator)` |
| `src/services/inference.py` | `InferenceService` (выбор провайдера, отказ без CUDA, пакетный вызов) |
| `src/tasks/segmentate.py` | сегментация листа, слияние масштабов, цветовая коррекция, `get_sheet_tile_range`, `save_as_geotiff`, пропуск готовых |
| `src/services/gee.py`, `src/utils/analysis.py`, `src/tasks/usability.py` | запрос SCL/Cloud Score+, `calculate_usability_metric` (правило 4-4-5-5), пропуск готовых листов, обработка ошибок |
| `src/tasks/classify.py` | объединение лет, морфология, правило `3 → 5`, запись |
| `src/utils/postclassify.py`, `src/tasks/save_db.py` | `clean`, `calculate_zonal_stats`, `UPSERT` в `assessment`, обработка ошибок поля |
| `src/tasks/export.py` | растеризация маски, сдвиг `+1`, COG-конвертация, транслитерация имён |
| `src/tasks/package.py` | экспорт GPKG, манифест 2.1, `check_missing_sheets`, состав ZIP |
| `src/tasks/push.py` | выбор последнего пакета (`_package_sort_key`), `rsync`, опрос статуса |
| `src/utils/timeutils.py` | `get_target_year` (граница ноября) |
| `src/core/config.py` | загрузка и валидация настроек |
| `dashboard.py`, `pipeline.py`, `src/services/notifier.py` | запуск цикла, плашки, Telegram |
| `src/sqlscripts/create_assessment_schema.sql` | создание схемы на пустой БД, совместимость с `save_db.py` (см. `etl-route.md`, шаг 1) |

Вне ETL, но без автотеста:

| Модуль | Не покрыто |
|---|---|
| `REPIKURR/deliver.py`, `watchdog.py` | все шаги доставки, предохранители, откат, очистка, `_is_stable`; проверены ручными экспериментами раундов 21, 38, 39 (`docs/round39-cleanup.md`), в репозитории тестов нет |
| `REPIKURR/repikurr/src/**` | юнит-тестов фронтенда нет (`package.json`: скрипты `dev`, `build`, `lint`, `preview`); есть только браузерный `smoke.mjs` |
| SQL-правило `valuation`/`bzdz` | эталонными значениями не проверяется автоматически (проверка — косвенная, через плагин: эталон `2212000055` даёт `tillage`) |
| Автозапуск ВМ (`cloud-function-autostart/main.py`) | проверен один раз реальной остановкой ВМ (round42), автотеста нет |
