# Требования к техническим средствам и программному обеспечению

Раунд 51, блок B3. Три роли: стенд ETL, сервер витрины (VPS), рабочее
место пользователя. Фактические значения прочитаны командами
(указаны в столбце «Источник»), без изменения состояния машин, на
2026-09-30. Где значение — требование, а не измерение, это оговорено.
Сокращения: `SS` = `docs/system-state.md`; `TPC` =
`docs/third-party-components.md`.

**Как читать «требования».** В репозитории нет заранее согласованных
минимальных/рекомендуемых характеристик (кроме старых из `legacy-diff.md`,
РО 2.1 и ПМИ 1.6). Ниже — **фактическая конфигурация**, на которой система
проверена, и **то, что из неё следует как минимально известное рабочее
значение**; пороги, ниже которых система работать не будет, в
большинстве случаев **не определялись** и так и помечены.

## 1. Стенд ETL (`192.168.251.190`, хост `user-MS-7E01`)

Роль: обработка (загрузка тайлов, сегментация на GPU, GEE, сборка пакета).
Совмещён с другими контейнерами других проектов (Taiga, open-webui, тестовый
клон REPIKURR и др. — `docker ps`), то есть **не выделенная** машина.

| Параметр | Значение | Источник |
|---|---|---|
| Процессор | 13th Gen Intel Core i5-13400, 16 логических CPU (2 потока на ядро), 1 сокет, макс. 4,6 ГГц (мин. 0,8 ГГц) | `lscpu` |
| Оперативная память | 62 ГиБ (занято 6,8 ГиБ, доступно 55 ГиБ на момент замера) | `free -h` |
| GPU | NVIDIA GeForce RTX 5070 Ti, 16 303 МиБ видеопамяти, драйвер 575.64, CUDA 12.9 | `nvidia-smi` |
| ОС | Ubuntu 24.04.2 LTS, ядро 6.2.0-39-generic | `/etc/os-release`, `uname -r` |
| Docker | Docker Engine 25.0.2, Compose v2.24.5 | `docker --version`, `docker compose version` |
| NVIDIA Container Toolkit | 1.17.8 | `nvidia-ctk --version` |
| Системный диск | `/dev/nvme0n1p2`, 915 ГБ, занято 505 ГБ (59 %), свободно 365 ГБ | `df -h` |
| Хранилище данных ETL | NFS `192.168.251.65:/Volume1/Data` → `/mnt/nfsdata`, 11 ТБ, занято 140 ГБ (2 %) | `mount`, `df -h /mnt/nfsdata` |
| Каталоги ETL | `HOST_INPUT_DIR=/mnt/nfsdata/PIKURR/inputs`, `HOST_OUTPUT_DIR=/mnt/nfsdata/PIKURR/outputs`, `HOST_PG_DATA=${HOST_OUTPUT_DIR}/pg_data` | `.env` стенда (только не секретные ключи) |

**Что известно о потребности ETL в ресурсах:**

- GPU с поддержкой CUDA **обязателен**: без активного `CUDAExecutionProvider`
  сегментация не стартует (`PIKURR/src/services/inference.py:25-33`, явный
  `RuntimeError`). Причина, по которой не используется TensorFlow:
  архитектура Blackwell (`sm_120`) — `docs/deploy-etl.md`, «Инференс: ONNX
  Runtime». Драйвер должен поддерживать CUDA ≥ 12.9 (`docs/deploy-etl.md`,
  «Требования»); образ — `nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04`
  (`PIKURR/Dockerfile:14`); проверено на драйвере 575.64.
- Видеопамять: при `INFERENCE__BATCH_SIZE=32` — ≈8,5 ГБ (`docs/deploy-etl.md`:
  с батчем 8 занято ≈2,7 из 16 ГБ, с 32 — ≈8,5 ГБ); минимально допустимый
  объём не определялся; размер батча подбирается под GPU.
- CPU/RAM: конкретные потребности ETL не измерялись в раунде 51; данные о
  времени листа — `docs/deploy-etl.md` (46 с на лист `N-35-10-В-а-3`,
  672 тайла, GPU) — справочно. Нижняя граница ресурсов — **не определялась**.
- Исходное требование из старого РО 2.1 («≥8 ядер, ≥32 ГБ, ≥4 ГБ
  видеопамяти, 4×2 ТБ RAID») **не подтверждено измерениями** ни в одном
  из раундов; стенд ему удовлетворяет с запасом по всем пунктам, кроме
  RAID (диска-массива нет; данные на NAS по NFS).
- Сетевой доступ (исходящий): geodzz.by (`https://www.geodzz.by/arcgis/rest/services/…`),
  `server.arcgisonline.com` (Esri), `mt1.google.com` (Google) —
  `.env_example`, `PIKURR/src/core/config.py:21-25`; Google Earth Engine
  (`earthengine-api`, `PIKURR/src/services/gee.py`); SSH/rsync к серверу
  доставки (`PIKURR/src/tasks/push.py`). Условия использования внешних
  сервисов не анализировались (правило раунда).

**ПО стенда (в контейнере `etl`)** — `PIKURR/Dockerfile`,
`PIKURR/requirements.txt`: Ubuntu 24.04 (образ CUDA 12.9.1 + cuDNN runtime),
Python 3.12 (venv `/opt/venv`), GDAL (`gdal-bin`, `libgdal-dev`), `gcc/g++`,
`rsync`, `openssh-client`; Python-пакеты (не запиненные, кроме
`onnxruntime-gpu==1.26.0`): `pydantic`, `pydantic-settings`, `sqlalchemy`,
`psycopg2-binary`, `pandas`, `numpy`, `rasterio`, `shapely`, `scikit-image`,
`tqdm`, `requests`, `tenacity`, `google-auth`, `earthengine-api`, `Pillow`,
`python-dotenv`, `streamlit`. Фактические версии внутри работающего
контейнера — `TPC`, раздел «Python ETL». БД ETL: `postgis/postgis:15-3.3`
(`docker-compose.yml:6`). Версия кода в образе — `ETL_GIT_COMMIT`
(`Dockerfile:66-67`).

## 2. Сервер витрины (VPS `geobotany.of.by`, `158.160.237.90`)

Роль: хранение боевых данных, GeoServer/GWC, React-клиент, TLS.
Прерываемая ВМ Yandex Cloud (принудительный останов раз в ≤ 24 ч; автозапуск —
Cloud Function, `SS` §1).

| Параметр | Значение | Источник |
|---|---|---|
| Процессор | 2 **долевых** (burstable) vCPU | `CLAUDE.md`, «Машины»; `nproc` = 2 |
| Оперативная память | 4 ГБ (3,8 ГиБ по `free -h`: занято 1,3 ГиБ, доступно 2,5 ГиБ) | `CLAUDE.md`; `free -h` |
| Диск | `/dev/vda1` 29 ГБ, занято 15 ГБ (52 %), свободно 14 ГБ | `df -h /` |
| ОС | Ubuntu 24.04.4 LTS | `/etc/os-release` |
| Docker | Docker Engine 29.8.1, Compose v5.5.1 | `docker --version`, `docker compose version` |
| Открытые порты | 80, 443 (Caddy); PostgreSQL `127.0.0.1:5432`, GeoServer `127.0.0.1:8090` — только loopback | `REPIKURR/docker-compose.vps.yml` (порты) |
| Контейнеры | `pikurr_vps_postgis` (`postgis/postgis:15-3.3`), `pikurr_vps_geoserver` (`kartoza/geoserver:2.24.2`), `pikurr_vps_react` (nginx+SPA), `pikurr_vps_caddy` (`caddy:2-alpine`) | `docker-compose.vps.yml`, `TPC` |
| Лимиты контейнеров на **работающей** ВМ | GeoServer `mem_limit=2048m`, `MAXIMUM_MEMORY=1024M`; PostGIS `mem_limit=1024m`, `shared_buffers=256MB`, `work_mem=32MB`, `max_connections=50`, `effective_cache_size=1GB`; react 128m; caddy 256m | `~/repikurr/docker-compose.vps.yml` на VPS (`grep`) |
| Лимиты в файле **репозитория** | GeoServer `mem_limit=3g`, `MAXIMUM_MEMORY=2048M`; PostGIS `mem_limit=1536m`, `shared_buffers=512MB` | `REPIKURR/docker-compose.vps.yml:31,39,49,59` |

**Расхождение (не исправлялось):** файл `docker-compose.vps.yml` в
репозитории **не совпадает** с работающим на VPS (md5 разные:
`6983e8a2…` в репозитории, `9ab62eb2…` на VPS, 2026-09-30) — лимиты памяти
раунда 41 (4 ГБ) в git не внесены. Скрипт `REPIKURR/deploy_backend_vps.sh
--check` сверяет `deliver.py`, `healthcheck.py`, `watchdog.py` и
вспомогательные файлы, но не compose-файл (`CLAUDE.md`, «Ловушки», про
`deploy_backend_vps.sh`). Основание конфигурации 4 ГБ —
`docs/round41-config-decision.md`, `docs/round40-capacity.md`.

**Что известно о пределах** (`CLAUDE.md`, «Машины и доступ», «Ловушки»):
кампания 6→5→4→3 ГБ; при 3 ГБ — реальная деградация GeoServer после
доставки (очередь квоты GWC), решение остановиться на 4 ГБ; критерий
неформальный: p95 < 2 с при 15 пользователях — на 4 ГБ выполнен
(p95 = 254 мс, `SS` §6); TLS-терминация Caddy на 2 vCPU стоит ×1,7–2,1
времени ответа. Числа с эмулятора на прод не переносятся.

**ПО сервера** (все в контейнерах): `TPC`, раздел «Прод (VPS)». Внешние
зависимости: домен и сертификат TLS (Caddy), Yandex Cloud (ВМ, Cloud Function
`pikurr-autostart`, таймерный триггер `pikurr-autostart-timer`, `SS` §1,
`REPIKURR/cloud-function-autostart/`), systemd-юниты на хосте:
`pikurr-vps-stack.service`, `pikurr-watchdog.service`
(`REPIKURR/pikurr-vps-stack.service`, `REPIKURR/pikurr-watchdog.service`),
sudo без пароля для пользователя развёртывания (`CLAUDE.md`).
`deliver.py`, `watchdog.py`, `healthcheck.py` выполняются на хосте
непосредственно (`/usr/bin/python3` хоста, клиент `psql` на хосте по
TCP к loopback-порту PostgreSQL — `REPIKURR/deliver.py:898-912`; юнит
`REPIKURR/pikurr-watchdog.service` рассчитан на пользователя `user` и
каталог `/home/user/repikurr` (стенд), юнит стека — на `/home/sgr/repikurr`
(VPS)); ETL на VPS **не выполняется**.

## 3. Рабочее место пользователя

| Что | Требование/факт | Источник |
|---|---|---|
| Витрина | Современный браузер с JavaScript. Проверялась только в Chromium (Playwright 1.63.0, окно 1400×900); другие браузеры и мобильные устройства в автоматических проверках не участвуют | `REPIKURR/tools/smoke/smoke.mjs:39`, `TPC` |
| Клиентские технологии витрины (для справки) | React 19.1.1, Leaflet 1.9.4, Vite 7.1.3 | `TPC`, `REPIKURR/repikurr/package.json` |
| QGIS для плагина | QGIS **не ниже 3.44** (`qgisMinimumVersion=3.44`, `qgisMaximumVersion=3.99`); разработан и проверен на QGIS 3.44.7-Solothurn (координаторская: `qgis --version`); сборки на Qt6 не проверялись | `pikurr_qgis/metadata.txt`, `docs/round48-qgis-plugin.md` |
| Сеть | HTTPS-доступ к `https://geobotany.of.by` (по умолчанию, настраивается в панели плагина); внешние подложки Esri/OSM — интернет | `pikurr_qgis/metadata.txt` (about), `pikurr_qgis/pikurr_panel_base.ui:46-48` |
| Экран, процессор, ОЗУ, диск, ОС АРМ | Требования не определялись (в старом РО 2.1: ≥2 ГГц, ≥8 ГБ, ≥1000 ГБ, монитор ≥19″, мышь — не подтверждено) | `legacy-diff.md`, РО 2.1 |

Плагин помечен в метаданных `experimental=True`; статус «прототип,
доработка запланирована» — `pikurr_qgis/PROTOTYPE_NOTICE.md` (текст записки
отстаёт от версии 1.2.0 — три перечисленных в ней ограничения устранены в
1.1.0/1.2.0 по `metadata.txt`, changelog; см. `user-scenarios.md`).

## 4. Модели

| Файл | Размер, Б | Статус | Источник |
|---|---|---|---|
| `inputs/models/onnx/two_opset13.onnx` | 47 209 600 | используется в ETL | `ssh 192.168.251.190 find inputs/models` |
| `inputs/models/two/1/saved_model.pb` | 3 196 172 | не используется (путь отката) | то же |
| `inputs/models/two/1/keras_metadata.pb` | 371 838 | то же | то же |
| `inputs/models/two/1/fingerprint.pb` | 56 | то же | то же |
| `inputs/models/one/1/saved_model.pb` | 3 242 191 | не используется | то же |
| `inputs/models/one/1/keras_metadata.pb` | 371 994 | то же | то же |
| `inputs/models/one/1/fingerprint.pb` | 56 | то же | то же |
| `inputs/models/one/1/variables/…`, `two/1/variables/…` | не выводились отдельно (каталог `inputs/models` — 143 МБ; ВНЗ 2024: по 47 577 973 Б) | — | `du`; `Ведомость_НЗ` |
| `models.config`, `batching_parameters.txt` | 245, 99 | нужны только для отката на TF Serving | то же |

Сами файлы весов в репозитории **не хранятся** (`.gitignore`), лицензия и
происхождение моделей — вне репозитория (`TPC`, «Известные пробелы»).

## 5. Фактические объёмы данных (основание требований к диску)

Все числа — чтение, 2026-09-30, с указанием машины.

**Стенд (NFS, каталог `outputs/`)**:

| Каталог | Размер | Файлов | Комментарий |
|---|---|---|---|
| `tiles/` | 7,4 ГБ | 912 листов + пул | пул `tiles/_pool` 6,2 ГБ; кэш тайлов не очищается автоматически |
| `predictions/predictions_veget` | 1,5 ГБ | 912 tif | |
| `predictions/predictions_usab` | 30 МБ | 2736 tif | 3 года × 912 |
| `predictions/predictions_final` | 1,6 ГБ | 912 tif | по годам |
| `predictions/geoserver_public/2025` | 560 МБ | 912 tif | COG |
| `predictions/geoserver_public/2025_before_cog_backup` | 1,3 ГБ | 912 tif | архив до перехода на COG (round29), не часть маршрута |
| `dist/` | 12 ГБ | 25 файлов (`ls` + `wc -l`) | накоплены пакеты разных дат; последний `pikurr_update_2025_2026-09-28_09-48.zip` = 537 341 400 Б (696 187 406 Б в распаковке) |
| `quarantine_20260916/` | 655 МБ | — | карантин round16 — **не удалять** (`CLAUDE.md`, «Не делать») |
| прочее (`tile_metrics.jsonl` 58 МБ, `negative_set_review` 45 МБ, отчёты JSON) | ≈ 0,1 ГБ | — | результаты разведок round8–17 |
| ETL-БД `pikurr_db` | 123 МБ | — | таблицы `agrifields` 81 МБ, `assessment` 9,4 МБ, `razgrafka` 3,9 МБ (`psql`) |
| `inputs/` | 196 МБ | — | модели 143 МБ, `sources` 53 МБ |

**Координаторская машина (репозиторий)**: `outputs/dist` ≈ 3,55 ГБ, 15
пакетов (`CLAUDE.md`, «Открытые вопросы»); `inputs/models` 102 МБ;
`demo_data` 159 МБ; `outputs/pg_data` — доступ запрещён пользователю
`sgr` (`git status`: «Отказано в доступе»).

**VPS**:

| Что | Размер | Источник |
|---|---|---|
| `data/geodata/2025` (растры года) | 561 МБ, 912 tif | `du`, `find` |
| карантинные копии `data/geodata/_removed_*` (2 шт.) | 558 МБ + 164 МБ | `du` (не удалять — `CLAUDE.md`) |
| БД `pikurr` целиком | 580 МБ (`agrifields` 90 МБ, `assessment` 15 МБ, `assessment_ready` 227 МБ, `assessment_ready_latest` 220 МБ) | `psql` |
| `geoserver_data/gwc` (кэш тайлов, квота 2 GiB) | 68 МБ | `du` |
| `backups/*.dump` (по 66 306 931 Б, ротация 10) | 380 МБ всего | `du`, статус доставки |
| Образы Docker | 4,3 ГБ (15 образов; «reclaimable» 154 МБ), контейнеры 723 МБ, тома 1,2 ГБ | `docker system df` |
| Свободное место | 14 ГБ из 29 ГБ; порог тревоги `healthcheck.py` — 3 ГБ | `df`, `healthcheck.py:443-469` |

**Что из этого следует для дисков (не требование, расчёт из фактов)**:
на год данных в текущем масштабе (912 листов, 59 209 полей) приходится
≈ 0,56 ГБ растров + ≈ 0,54 ГБ пакет (сжатый) + ≈ 0,07 ГБ дамп бэкапа;
доставка временно удерживает вместе пакет + распаковку + карантин старого
года (крупнейший разовый прирост — карантин года ≈ 0,56 ГБ, `healthcheck.py:443-460`,
`docs/round39-cleanup.md`). Автоматической очистки карантинов/бэкапов/
статус-файлов на VPS нет (`CLAUDE.md`, «Ловушки»; `SS` §7).
