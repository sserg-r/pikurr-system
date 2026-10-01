# Технологический маршрут ETL в том виде, как он реализован

Раунд 51, блок B1. Источник — код `PIKURR/src/`, `PIKURR/pipeline.py`,
`PIKURR/dashboard.py`, конфигурация `.env` стенда (только не секретные
ключи `INFERENCE__*`, `DZZ__*`, `PATHS__*`, `HOST_*`, `DB__HOST/PORT/NAME`),
данные стенда (чтение). Сверка со старыми документами — `legacy-diff.md`
(разделы А1–А2). Сокращения путей: `dl` = `PIKURR/src/tasks/download.py`,
`seg` = `…/segmentate.py`, `usab` = `…/usability.py`, `cls` =
`…/classify.py`, `pc` = `PIKURR/src/utils/postclassify.py`, `gee` =
`PIKURR/src/services/gee.py`; остальные — от корня репозитория.

## 0. Общая схема

Порядок (`PIKURR/pipeline.py:28-56`, `PIKURR/dashboard.py:196-266`):

```
initialize → download → segmentate → usability → classify → save_db → export → package
                                                                              ↘ push (отдельно)
```

- Всего 8 шагов «полного цикла»; 9-й — `push` — отдельная кнопка
  дашборда и не входит в цикл (`dashboard.py:170-176`).
- Между шагами данные передаются **через диск и БД**, а не в памяти;
  у большинства шагов есть пропуск уже готового результата (возобновляемость,
  см. по шагам).
- Шаги, использующие внешние сервисы: `download` (geodzz.by, Esri,
  Google), `usability` (Google Earth Engine), `push` (SSH/rsync на сервер
  витрины). Остальные работают локально.
- Ошибка `pipeline.py` печатается с трассировкой и процесс «спит» 600 с,
  не завершаясь (`pipeline.py:59-66`) — чтобы контейнер не падал и лог
  можно было прочитать.
- Запуск: `docs/deploy-etl.md` («Запуск пайплайна»). Расписания нет
  (grep `schedule|cron|apscheduler` по `PIKURR/` — пусто).

**Каталоги** (`PIKURR/src/core/config.py:88-146`; в контейнере
`PATHS__DATA_INPUT=/data_input`, `PATHS__DATA_OUTPUT=/data_output`,
на стенде — `HOST_INPUT_DIR=/mnt/nfsdata/PIKURR/inputs`,
`HOST_OUTPUT_DIR=/mnt/nfsdata/PIKURR/outputs`, том NFS 11 ТБ с сетевого
хранилища `192.168.251.65:/Volume1/Data`, `mount` на стенде):

| Что | Путь (относительно `data_input`/`data_output`) | Размер на стенде (чтение, 2026-09-30) |
|---|---|---|
| Исходные слои | `sources/agrifields.zip`, `sources/razgrafka_SK63.zip` | 53 МБ всего (`agrifields.zip` 53 886 798 Б, `razgrafka_SK63.zip` 818 181 Б) |
| Модели | `/models` ← `inputs/models` (ONNX: `onnx/two_opset13.onnx`) | 143 МБ каталог; ONNX-файл 47 209 600 Б |
| Тайлы z=17 | `tiles/<лист>/{z}_{x}_{y}.jpg` | 7,4 ГБ (`tiles`), из них пул `tiles/_pool` 6,2 ГБ |
| Маска растительности | `predictions/predictions_veget/<лист>.tif` | 1,5 ГБ, 912 файлов |
| Маска «используемости» | `predictions/predictions_usab/<год>/<лист>.tif` | 30 МБ, 2736 файлов (3 года × 912) |
| Итоговая классификация | `predictions/predictions_final/<год>/<лист>.tif` | 1,6 ГБ, 912 файлов |
| Публичные растры | `predictions/geoserver_public/<год>/<лист>.tif` | `2025`: 560 МБ, 912 файлов (рядом каталог-бэкап `2025_before_cog_backup` 1,3 ГБ — не часть маршрута) |
| Пакеты обновлений | `dist/pikurr_update_<годы>_<дата>.zip` | 12 ГБ (каталог `dist` на стенде) |
| ETL-БД | `pg_data` (том PostgreSQL) | 123 МБ БД (`pg_database_size`) |

Листов проекта — **912** (`trapeze_serv`, `psql` на стенде), т. е. 912
трапеций 1:10 000 из 21 280 листов национальной разграфки.

**Параметры окружения** (`.env` стенда, не секретные): `DZZ__USE_EXPORT=true`,
`DZZ__PREFER_EXPORT=true`, `DZZ__USE_POOL=true`, `DZZ__BLOCK_TILES=16`,
`DZZ__BLOCK_WORKERS=1`, `DZZ__TILE_WORKERS=4`, `DZZ__BLOCK_DELAY_MIN/MAX=0.5/1.5`,
`DZZ__TILE_DELAY_MIN/MAX=0.1/0.4`, `DZZ__BLOCK_REST_AFTER_MIN/MAX=25/35`,
`DZZ__BLOCK_REST_MIN/MAX=60/120`, `DZZ__SESSION_MAX_MINUTES=150`,
`DZZ__EXPORT_FAILURE_THRESHOLD=5`, `INFERENCE__BATCH_SIZE=32`,
`INFERENCE__PROVIDER=CUDAExecutionProvider`,
`INFERENCE__ONNX_MODEL_PATH=/models/onnx/two_opset13.onnx`,
`DBTABLES__TRAP=trapeze_serv`, `DBTABLES__AFIELDS=agrifields`,
`DBTABLES__RAZGR=razgrafka`. Значения по умолчанию в коде совпадают
(`PIKURR/src/core/config.py:26-73,176-190`), кроме указанных в `.env`.

**Что видит оператор (общее)** (`PIKURR/dashboard.py`, `PIKURR/src/utils/progress.py`):

- Streamlit-панель «PIKURR: Панель управления» (`dashboard.py:43`), порт
  контейнера 8501 → хоста 8505 (`docker-compose.yml:88`).
- Боковая панель «Статус системы»: подключение к БД (пинг `SELECT 1`),
  индикатор модели (файл `.onnx` существует и провайдер CUDA собран в
  `onnxruntime`; **не** проверка реальной инициализации CUDA —
  `docs/deploy-etl.md`, «Известное ограничение»), «GEE Service Account»
  (всегда «✅», без проверки), пути входа/выхода (`dashboard.py:46-97`).
- Плашки этапов 1–8 (ожидание → «⏳» → «✅ N. …: OK»), 9 — отправка
  (`dashboard.py:160-193`, `:210-262`); при исключении — «ОШИБКА
  ВЫПОЛНЕНИЯ», трассировка в журнале, уведомление в Telegram
  (`dashboard.py:265-282`).
- «Системный журнал»: перехват `logging` и `print()` в окно 450 px
  (`dashboard.py:100-133`, `:196-266`).
- Строки прогресса `ProgressReporter` (каждые 30 с, окно скорости 600 с —
  `config.py:69-73`): счётчики внешнего/внутреннего цикла (лист/тайлы),
  скорость, оценка окончания (`src/utils/progress.py`). Выводятся через
  `logging`, поэтому попадают в «Системный журнал» (перехват корневого
  логгера, `dashboard.py:100-133`). С раунда 56 (коммит `dff9840`) строки
  выдают и шаги 6 (`save_db`) и 7 (`export`) — до этого эти два шага
  показывали ход через `tqdm` в stderr, который панель не перехватывает.
- После цикла — таблица «5 последних записей `assessment`» и общий счётчик
  (`dashboard.py:284-303`).
- Опционально Telegram (`TELEGRAM__TOKEN`, `TELEGRAM__CHAT_ID`):
  «запущен полный цикл», «успешно завершён», «аварийно остановлен + текст
  ошибки ≤200 символов» (`dashboard.py:198-282`, `src/services/notifier.py:9-43`).
  Есть ли значения на стенде — не проверялось (секреты).

---

## 1. `initialize` — загрузка исходных слоёв в БД

Файл `PIKURR/src/tasks/initialize.py`, класс `InitializeTask`.

- **Назначение**: залить в PostGIS сетку листов и контуры полей, построить
  список листов проекта и (пере)создать схему результатов.
- **Вход**: `sources/razgrafka_SK63.zip`, `sources/agrifields.zip`
  (`initialize.py:19,25`); SQL `PIKURR/src/sqlscripts/get_trapeze_on_agrifields.sql`
  и `create_assessment_schema.sql` (`config.py:150-165`).
- **Что делает**:
  1. `ogr2ogr -f PostgreSQL` для `razgrafka` с `-select m10000_id,n10000`;
     для `agrifields` — все поля. Общие параметры: `/vsizip/…`, `-t_srs
     EPSG:4326`, `-nln <таблица>`, `-nlt PROMOTE_TO_MULTI`, `-lco
     SPATIAL_INDEX=GIST`, `-lco GEOMETRY_NAME=geom`, `-overwrite`
     (`initialize.py:68-100`). Пароль передаётся в `PGPASSWORD`.
  2. SQL `SELECT DISTINCT r.n10000 FROM razgrafka r JOIN agrifields a ON
     ST_Intersects(r.geom, a.geom)` → таблица `trapeze_serv(name, serv='dzz')`
     с `if_exists='replace'` (`initialize.py:32-49`,
     `PIKURR/src/sqlscripts/get_trapeze_on_agrifields.sql:1-2`). Если пересечений нет — только
     сообщение `WARNING: No intersection…` (`initialize.py:53`).
  3. Выполнение `create_assessment_schema.sql` (`initialize.py:53-64`,
     `DatabaseService.execute_sql_file`).
- **Выход (БД)**: таблицы `razgrafka` (21 280 строк), `agrifields`
  (59 209), `trapeze_serv` (912) — числа стенда (`psql`, 2026-09-30);
  схема результатов.
- **Порядок/условия**: первый шаг цикла; **не** возобновляемый — перезапись
  таблиц (`-overwrite`, `replace`), т. е. повторный запуск обнуляет
  `agrifields`/`razgrafka`/`trapeze_serv` ETL-БД.
- **Наблюдение (не исправлялось, не входит в задачу)**: живая ETL-БД на
  стенде отличается от того, что описывает `create_assessment_schema.sql`
  версии `SCHEMA_VERSION=3`: таблица `assessment` там — `id SERIAL PRIMARY KEY`,
  `stats jsonb`, `description text`, `updated_at timestamp`, а представления
  `assessment_ready` и `assessment_ready_latest` — обычные VIEW, материализованных
  нет (`psql \d assessment`, `pg_matviews` пуст, 2026-09-30). В репозитории
  DDL — `fid SERIAL PRIMARY KEY`, `id INTEGER NOT NULL` (без DEFAULT),
  `stats VARCHAR` (`PIKURR/src/sqlscripts/create_assessment_schema.sql:78-89`) и материализованные
  представления. Что при повторной инициализации ETL-БД «с нуля» вставка
  `save_db.py:53-58` (не задаёт `id`) была бы отвергнута ограничением
  `NOT NULL` — **не проверялось** (запускать `initialize` запрещено правилами
  раунда); это предположение по чтению DDL и кода.
- **Что видит оператор**: плашка «1. Инициализация», строка
  `Executing: ogr2ogr …` (без пароля), `Creating assessment schema…` /
  `Assessment schema created successfully.` (`initialize.py:53-64,98`).

## 2. `download` — загрузка тайлов z=17

Файл `dl`, класс `DownloadTilesTask`. Подробности логики выбора источника —
`legacy-diff.md`, А2-1.

- **Назначение**: получить для каждого листа проекта все тайлы уровня 17.
- **Вход**: список листов и их геометрия `trapeze_serv ⨝ razgrafka` по
  `name = n10000` (`dl:280-292`); `.env` `TILESERVICES__*`, `DZZ__*`;
  необязательный `outputs/affected_sheets.json` (`config.py:67`).
- **Ключевые параметры** (значения на стенде = по умолчанию,
  `config.py:26-73`): `z=17` (`dl:615`); блок 16×16 тайлов = 4096×4096 px
  (`config.py:32`); экспорт `jpg`, качество 75, билинейная интерполяция,
  `bboxSR=imageSR=3857` (`PIKURR/src/services/dzz_export.py:69-78`); таймаут блока
  120 с, тайла 15 с (`dzz_export.py:116,155`); ретраи 429/503 — до 4 с
  экспоненциальной паузой (`src/utils/http_retry.py`, `max_retries=4`);
  403/401 — остановка задачи (`http_retry.py:60`); `block_workers=1`,
  `tile_workers=4`; проверка качества `passes_quality` (доля пикселей R==G
  < 0,7, `dl:44-54`).
- **Алгоритм на лист** (`dl:615-713`):
  1. диапазон тайлов листа по крайним точкам внешнего контура геометрии
     (`dl:294-311`, `getTileIndex`);
  2. **Фаза A** — блоки geodzz через `exportImage` (`dl:387-477`): проверка
     «уже на диске», затем «из пула» (жёсткие ссылки `os.link`, запасной
     вариант — копия, `dl:367-383`), затем маркер обработанного блока
     (`dl:361-365`), затем сетевой запрос блока, нарезка на 256×256,
     проверка качества, запись в пул только годных тайлов;
  3. **Фаза B** — добор недостающих тайлов по одному: `dzz-export` →
     `dzz-tile` (тайловый кэш) → `esri` → `google` (`dl:481-539`);
  4. проверка полноты сетки: недостающие тайлы → `<лист>_missing.json`
     рядом с папкой листа (`dl:586-611`).
- **Лимиты нагрузки на сторонний сервис**: отдых после непрерывной работы
  (25–35 мин работы → 60–120 с паузы, `dl:192-226`); лимит сессии 150 мин
  (после него — штатное завершение, следующий запуск продолжит,
  `dl:230-241`, `dl:743-751`); предохранитель отказов каталога (5 отказов
  подряд на разных координатах → `exportImage` отключается до конца
  прогона, `dl:169-188`); проба каталога перед первым листом (`dl:245-278`,
  вызов — `dl:731`).
- **Исключения**: листы из `affected_sheets.json` (87 шт., `docs/round16-esri-switch.md`)
  идут только Esri → Google (`dl:620-625`, `dl:495-499`).
- **Выход**: `tiles/<лист>/17_<x>_<y>.jpg` (`dl:315-322`); общий пул
  `tiles/_pool/17_<x>_<y>.jpg`, `tiles/_pool/_blocks/17_<bcol>_<brow>.done`
  (`dl:336-365`); служебные `tiles/<лист>_missing.json`.
- **Порядок/условия**: после `initialize`; возобновляем — существующие
  непустые тайлы не запрашиваются (`dl:320-322`). Пул **не обновляется
  автоматически**: пока пул не очищен, обновлений мозаики источника система
  не увидит (`docs/deploy-etl.md`, «Пул тайлов geodzz»).
- **Исключение при 403**: `DownloadBanned` (`dl:762-765`) — цикл
  останавливается (плашка красная).
- **Что видит оператор**: `Found N trapezes for processing`; на лист —
  «Лист X: NxM тайлов», счётчики блоков и источников, «потайловый добор
  для K тайлов», предупреждения о недостающих тайлах (`dl:604-607`),
  строки прогресса (блоки `i/N`, источники), сообщения об отдыхе и лимите
  сессии, `ERROR` при отключении `exportImage`.

## 3. `segmentate` — семантическая сегментация листа

Файл `seg`, класс `SegmentationTask`; `src/services/inference.py`.

- **Назначение**: получить растр классов растительности на весь лист.
- **Вход**: `tiles/<лист>/…jpg`; границы листа из `razgrafka`
  (`seg:70-97`); ONNX-модель `INFERENCE__ONNX_MODEL_PATH`.
- **Ключевые параметры**: окно 256×256, перекрытие 30 px (`seg:44,123,132`),
  нормализация `/255.0` (`seg:49`), `argmax` по каналам (`seg:57`),
  пакет `INFERENCE__BATCH_SIZE` (32), провайдер CUDA (при отсутствии — ошибка
  запуска, `inference.py:25-33`), два масштаба (1,0 и 0,5, `seg:123-135`).
- **Алгоритм**: склейка тайлов листа в канвас по истинной границе листа,
  недостающие тайлы — чёрный плейсхолдер (`src/utils/image.py:131-247`;
  `<лист>_gaps.json`, `seg:101-117`) → нарезка `split_image` → инференс →
  `merge_imageset` → слияние двух масштабов (`seg:144-145`) → цветовая
  коррекция класса «прочее» (`seg:151-175`) → GeoTIFF (`seg:179-203`).
- **Выход**: `predictions/predictions_veget/<лист>.tif`, uint8, 1 канал,
  EPSG:4326, LZW (`seg:194-199`), значения 0–4.
- **Порядок/условия**: листы, у которых есть непустая папка тайлов и **нет**
  готового `.tif` (`seg:209-214`) — возобновляем. Ошибка на листе логируется
  и цикл идёт дальше (`seg:224-227`).
- **Что видит оператор**: строки прогресса «лист / фрагменты», `WARNING` о
  недостающих тайлах с долей плейсхолдер-пикселей (`seg:110-115`), `ERROR`
  на сбойном листе.
- **Скорость** (справочно, не замер раунда 51): 46 с на лист `N-35-10-В-а-3`
  (672 тайла) на GPU RTX 5070 Ti — `docs/deploy-etl.md`, «Инференс: ONNX
  Runtime».

## 4. `usability` — временной ряд Sentinel-2 и «признак обработки»

Файлы `usab`, `gee`, `PIKURR/src/utils/analysis.py`, `PIKURR/src/utils/timeutils.py`.

- **Назначение**: по Sentinel-2 SCL за 3 сезона определить пиксели с
  признаком хозяйственной обработки.
- **Вход**: границы листа из `razgrafka` (`usab:41-62`); Earth Engine
  (сервисный аккаунт `GEE__SERVICE_ACCOUNT`, проект `GEE__PROJECT`,
  `gee:10-15`).
- **Ключевые параметры**: 3 года (`usab:64-65`; год оценки — `timeutils.py:7`);
  период 15.04–15.10 (`gee:38`); облачность сцены < 20 % (`gee:44,57-58`);
  Cloud Score+ `cs_cdf ≤ 0,80` → SCL=12 (`gee:42-54`); суточные мозаики
  (`gee:63-78`); разрешение 10 м, EPSG:4326 (`gee:84-93`); предел площади 25 км²
  (`gee:34-35`); ретраи ×5 (`gee:23,99`); критерий пикселя — окна SCL
  `4,4,5,5` / `5,5,4,4`, не менее 4 валидных наблюдений
  (`analysis.py:16-28`).
- **Выход**: `predictions/predictions_usab/<год>/<лист>.tif` (uint8, 1
  канал, `nodata=0`, LZW — `usab:92-105`) — счётчик найденных окон на пиксель.
- **Порядок/условия**: для каждого из 3 лет и каждого листа проекта; уже
  существующий `.tif` пропускается (`usab:128-130`); ошибка на листе
  логируется, лист пропускается без файла (`usab:89-90`) — на следующем
  запуске будет повтор.
- **Что видит оператор**: `Target years: […]`, `Total trapezes: N`,
  `Processing year: Y`, прогресс «год / поля», `Error processing … for
  year …`.

## 5. `classify` — объединение маски растительности и «обработки»

Файл `cls`, `PIKURR/src/utils/timeutils.py`.

- **Назначение**: получить итоговый растр классов 0–5.
- **Вход**: `predictions_veget/<лист>.tif`, `predictions_usab/<год>/<лист>.tif`
  за 3 года.
- **Алгоритм** (`cls:45-150`): `any` по годам → `closing(disk(1))` →
  `sieve(10, connectivity=4)` → `resize` к размеру маски растительности →
  `mask_condition = (маска>0) & (растительность==3)` → значение 5 →
  запись.
- **Выход**: `predictions/predictions_final/<год>/<лист>.tif`, uint8,
  `nodata=255`, LZW, EPSG:4326 (`cls:131-146`); «год» — последний из 3
  (`cls:130`).
- **Порядок/условия**: для каждого листа проекта; при отсутствии маски
  растительности лист пропускается молча (`cls:52-53`); при отсутствии
  масок usab за все годы — «нет обработки» (нулевой массив, `cls:78-79`).
  **Не пропускает** уже готовые файлы — перезаписывает.
- **Что видит оператор**: `Classification years range: [...]`,
  `Target directory: …` (`print`), прогресс «лист».

## 6. `save_db` — статистика по полям в БД

Файл `PIKURR/src/tasks/save_db.py`; `pc:61-160`.

- **Назначение**: для каждого поля посчитать доли классов и записать в
  `assessment`.
- **Вход**: `agrifields` ⨝ `razgrafka` по `ST_Intersects`
  (`array_agg(n10000) AS frames`, `save_db.py:34-45`); растры
  `predictions_final/<год>/<лист>.tif`; год — `get_target_year()`
  (`save_db.py:97`).
- **Алгоритм**: слияние растров листов, пересекающих поле (`merge`,
  `nodata=255`, `pc:86`) → маска полигоном `crop=True, filled=False, pad=True,
  pad_width=2` (`pc:121`) → `clean()` (закрытие `disk(2)`, `sieve` 3 px,
  `pc:17-52`) → доли классов без 255 (`pc:151-159`) → JSON строкой.
- **Выход (БД)**: `INSERT INTO assessment (fid_ext, year, stats, updated_at)
  … ON CONFLICT (fid_ext, year) DO UPDATE` (`save_db.py:53-58`); ключ —
  `nr_user` поля (`fid_ext`); пример записи: `{"0": 0.0847, "2": 0.0166,
  "3": 0.4249, "5": 0.4738}`. На стенде: год 2025, 55 784 строки (при 59 209
  полях; поля без пересекающегося растра или без результата пропускаются,
  `save_db.py:82-91`).
- **Порядок/условия**: возобновляем идемпотентно (UPSERT), но
  пересчитывает все поля. Ошибка на поле логируется и не прерывает цикл
  (`save_db.py:105-107`).
- **Зависимость от порядка листов** (отчёт `docs/round55-consistency.md`,
  `docs/round56-overlap-docs.md`): `array_agg(n10000)` в `get_fields`
  (`save_db.py:34-45`) собирается без `ORDER BY`, а `merge(..., nodata=255)`
  (`postclassify.py:86`) берёт в зоне перекрытия растров листов пиксель
  первого по порядку источника. Порядок листов зависит от плана/физического
  порядка строк БД на момент расчёта; при повторном расчёте `stats` участков,
  пересекающих 2+ листов, может отличаться. Участки на одном листе
  воспроизводятся полностью. Масштаб на стенде (год 2025): 7 484 участка на
  2+ листах (13,4 % участков) из 55 784; растры листов перекрываются на
  полосу в один тайл z17 (256 px) вдоль общих границ.
- **Многочастные `nr_user`**: у 3 425 значений `nr_user` в `agrifields`
  несколько строк с разной геометрией; `save_stats` пишет по `ON CONFLICT
  (fid_ext, year)`, поэтому в `assessment` остаётся результат последней
  обработанной части (раунд 56, блок A3: у 693 проверенных ключей с 2+ листами
  `stats` из пакетов A и B ближе всего к расчёту одной и той же части; точное
  совпадение с расчётом одной из частей — у 650 (A) и 652 (B) ключей).
- **Что видит оператор**: `Processing N fields for year Y`, строки прогресса
  `PROGRESS save_db | участок i/N (%) <nr_user> | участки 1/1 | … участок/с |
  прошло … | осталось ~…` (каждые 30 с), итоговая строка `PROGRESS save_db |
  завершено | обработано … | пропущено … | не получено … | время … |
  средняя скорость …`, сообщения `Error processing field …` (с раунда 56;
  прежде — индикатор `tqdm` «Saving stats» в stderr, не виден в панели).

## 7. `export` — публичные растры

Файл `PIKURR/src/tasks/export.py`.

- **Назначение**: подготовить растры года для публикации: убрать всё вне
  полей и пересобрать в Cloud-Optimized GeoTIFF.
- **Вход**: `predictions_final/<год>/<лист>.tif`; геометрии `agrifields`,
  пересекающие лист по `a.geom && r.geom` (`export.py:82-99`).
- **Алгоритм**: `rasterize(геометрии, all_touched=True)` → `(данные + 1) ×
  маска` (`export.py:163`) → nodata=0 → запись → `gdal_translate -of COG -co
  COMPRESS=LZW -co RESAMPLING=NEAREST -co BLOCKSIZE=512` (`export.py:25-46`,
  `:33`). Смещение `+1`: значения растра — код класса + 1 (1 = лес … 6 =
  обработка), 0 = фон/прозрачность.
- **Имя файла**: кириллица листа → латиница по таблице `trans_tab`
  (`export.py:58-68`); каталог `predictions/geoserver_public/<год>/`
  (`export.py:115`).
- **Порядок/условия**: год — `get_target_year()`; лист без геометрий
  полей пропускается (`export.py:123-128`); ошибка на листе логируется
  (`export.py:179-180`).
- **Что видит оператор**: `Exporting N trapezes for year Y`, строки
  прогресса `PROGRESS export | лист i/N (%) <лист> | листы 1/1 | … лист/с |
  прошло … | осталось ~…` (каждые 30 с), итоговая строка `PROGRESS export |
  завершено | …`, предупреждения GDAL `CPLE_IllegalArg … BLOCKXSIZE can only
  be used with TILED=YES` (по одному на лист), `Export complete.` (с
  раунда 56; прежде — `tqdm` «Exporting Public Data» в stderr, не виден в
  панели).

## 8. `package` — пакет обновления

Файл `PIKURR/src/tasks/package.py`; манифест v2.1 (`package.py:217`).

- **Назначение**: собрать ZIP-пакет для доставки на сервер витрины.
- **Вход**: таблицы `agrifields`, `razgrafka`, `assessment` ETL-БД;
  `geoserver_public/<год>/*.tif` (годы — все каталоги-годы с tif,
  `collect_raster_years`, `package.py:97-107`); `create_assessment_schema.sql`.
- **Алгоритм**: экспорт слоёв GPKG `ogr2ogr` (`agrifields`, `razgrafka`,
  `assessment` с `stats::text`, без `valuation`, `package.py:71-75`) →
  копия растров в `rasters/<год>/` → копия SQL-схемы → `manifest.json` →
  ZIP_DEFLATED (`package.py:274`); сверка полноты по `trapeze_serv`
  (`check_missing_sheets`, транслитерация имён; только `ERROR` в лог,
  `package.py:109-143`).
- **Выход**: `dist/pikurr_update_<годы>_<YYYY-MM-DD_HH-MM>.zip`; печатает
  `OUTPUT: <путь>` (`package.py:282`). Содержимое — `data-io.md`, §4.
- **Порядок/условия**: последний шаг цикла; временный каталог `temp_build`
  очищается (`finally`, `package.py:284-287`). **Перед сборкой** нужна
  проверка содержимого ETL-БД (годы, число строк, `updated_at`) —
  правило `CLAUDE.md` «Ловушки» (round38).
- **Что видит оператор**: `Exporting vectors…`, `Exporting layer: …`,
  `Copying rasters …`, `Creating archive: …`, `Package created successfully!
  Years: […]`; `ERROR` по недостающим листам.

## 9. `push` — отправка пакета (вне цикла)

Файл `PIKURR/src/tasks/push.py`.

- **Назначение**: передать последний пакет на сервер витрины и дождаться
  подтверждения доставки.
- **Ключевые параметры** (переменные окружения контейнера): `DELIVERY_HOST`
  (если пуст — отправка пропускается с предупреждением), `DELIVERY_USER`
  (по умолчанию `user`), `DELIVERY_SSH_KEY` (`/root/.ssh/id_rsa`),
  `DELIVERY_INBOX`, `DELIVERY_STATUS_DIR`, `DELIVERY_KNOWN_HOSTS`,
  `DELIVERY_STATUS_TIMEOUT` (600 с) (`push.py:32-45`).
- **Алгоритм**: последний по дате в имени пакет (`push.py:52-60`) → `rsync
  -avz --progress -e ssh …` (`push.py:156-160`) → опрос статус-файла
  доставки на сервере каждые 5 с до `ok: true/false` (`push.py:78-140`);
  промежуточный статус `ok: null` не считается результатом.
- **Выход**: строка `PUSHED: <пакет> → <адрес>`; при ошибке доставки —
  исключение с шагом и текстом ошибки сервера.
- **Порядок/условия**: только кнопка «ОТПРАВИТЬ ПАКЕТ НА СЕРВЕР» (активна,
  если задан `DELIVERY_HOST`) либо `python -m src.tasks.push` /
  `package_and_push.sh`. Что дальше происходит на сервере — `data-io.md`, §4,
  `operations.md`.
- **Что видит оператор**: «Отправка … → …», «Ожидание подтверждения
  доставки…», «Доставка в процессе, шаг: …», «Доставка подтверждена:
  …, гранул в мозаике после обработки: N».

## 10. Сведения, которые не относятся ни к одному шагу

- **Прогресс и устойчивость**: ProgressReporter — только логирование, на
  результаты не влияет (`src/utils/progress.py`).
- **Файлы вне маршрута, лежащие рядом**: `PIKURR/src/tasks/segmentate_old.py`
  (не отслеживается git, старая версия сегментации; импортируется устаревшим
  локальным `test_segmentation.py`); `PIKURR/src/services/_archive/
  inference_ovms_tfserving.py` (путь отката на TF Serving, не используется);
  `PIKURR/scripts/provenance_snapshot.py` (разовый скрипт).
- **Стадия «инициализация путей» из старого маршрута** (ОП 3.1) в коде
  отдельной не выделена: каталоги создаются по месту (`mkdir(parents=True,
  exist_ok=True)`, например `seg:207`, `dl:316-317`).
- **Стадии «ранжирование тайл-сервисов», «Sentinel-2 NDVI», «публикация в
  GeoServer»** в ETL отсутствуют (`legacy-diff.md`, А1/А2).
