# Сценарии эксплуатации — указатель

Раунд 51, блок B4. Не переписывает `CLAUDE.md` и `docs/system-state.md`
(`SS`) — собирает указатель: **сценарий → где описан → чем проверяется**.
Существование каждого файла/скрипта проверено `ls` на 2026-09-30; флаги
скриптов — чтением самих скриптов. Процедуры, которые меняют прод, стенд
или эмулятор, в раунде 51 **не выполнялись** — статус «проверено фактом»
взят из отчётов раундов и помечен ссылкой.

## 1. Сценарии

| # | Сценарий | Где описан | Чем проверяется | Замечания |
|---|---|---|---|---|
| 1 | **Развёртывание ETL-стенда** (образ `etl`, БД `db`, модели, `.env`) | `docs/deploy-etl.md` («Первоначальная настройка», «Запуск пайплайна»), `.env_example`, `PIKURR/Dockerfile`, `docker-compose.yml` | панель Streamlit (`http://<стенд>:8505`): зелёные «Database: Connected», «Inference (ONNX Runtime, CUDAExecutionProvider)» (`PIKURR/dashboard.py:46-97`); `docker compose ps` | индикатор модели не гарантирует CUDA-инициализацию (`deploy-etl.md`, «Известное ограничение»); запускать `docker compose -f <файл>`; для `etl` на стенде — оба файла `-f docker-compose.yml -f docker-compose.override.yml` (`CLAUDE.md`, «Ловушки») |
| 2 | **Запуск обработки (полный цикл / по шагам)** | `docs/deploy-etl.md` («Запуск пайплайна», варианты А/Б/В), `docs/facts/etl-route.md` | плашки этапов 1–8 в дашборде; файлы результатов в `outputs/predictions/…`; `docker logs` | расписания нет; сеансы загрузки ограничены 150 мин (возобновление запуском заново) |
| 3 | **Обновление исходных данных (`agrifields.zip`)** | `docs/deploy-etl.md` («Полный цикл обновления данных») | `initialize` отработал (`Executing: ogr2ogr…`); число строк `agrifields`/`trapeze_serv` | `initialize` перезаписывает таблицы ETL-БД |
| 4 | **Принудительное обновление снимков (очистка пула тайлов)** | `docs/deploy-etl.md` («Пул тайлов geodzz») | пул очищен вместе с `_blocks/`; папки листов очищены; повторный `download` запрашивает блоки | иначе система не увидит новой съёмки |
| 5 | **Сборка пакета обновления** | `SS` §5.1; `CLAUDE.md` («Ловушки» — правило round38; «Текущее состояние» — провенанс); `docs/round38-data-incident.md` | манифест 2.1 внутри ZIP (`unzip -p … manifest.json`): годы, `row_counts`, `raster_counts_by_year`, `etl_git_commit`; сверка sha256 | **до сборки** проверить содержимое ETL-БД (годы, `updated_at`, число строк); единственный источник — `pikurr-system-db-1` на стенде |
| 6 | **Отправка пакета** | `docs/deploy-etl.md` (кнопка/`push`/`package_and_push.sh`), `PIKURR/src/tasks/push.py`, `REPIKURR/delivery-dispatch.sh` (ограниченный SSH-ключ), `docs/round22-vps-deploy.md` (задача 7) | `PUSHED: …` и подтверждение статус-файла `ok: true` (`push.py`) | отчёт о содержимом пакета и подтверждение пользователя **до** передачи на VPS (`CLAUDE.md`, round38) |
| 7 | **Доставка пакета на сервер витрины** | `SS` §2 п. 5, §5.2; `docs/deploy-repikurr-vps.md`; `docs/round19-delivery-audit.md`, `round20-delivery-fixes.md`, `round21-delivery-hardening.md`, `round25`, `round26`; `REPIKURR/deliver.py`, `REPIKURR/watchdog.py` | `status/<пакет>.json`: `ok: true`, `healthcheck.ok: true`, `seed_gwc_cache`, `backup.ok`; `journalctl -u pikurr-watchdog.service -f`; `healthcheck.py --base-url …` | флаги `deliver.py`: `--cleanup`, `--retention-days`, `--dry-run`, `--shrink-threshold`, `--allow-shrink`, `--allow-year-change` (`REPIKURR/deliver.py:1824-1860`); копировать файл в `inbox/` через `.part`-суффикс, при ложном отказе `unpack` — `mv`, не `cp` (`CLAUDE.md`, «Ловушки») |
| 8 | **Откат данных** (неудачная доставка/ошибочная подмена) | `SS` §5.5; `CLAUDE.md` («Провенанс… `pg_dump`-бэкап»); `docs/round39-cleanup.md` (блок B — обкатка `pg_restore`) | `pg_restore -d <db> REPIKURR/backups/<файл>.dump`; затем `REFRESH` представлений, `healthcheck.py` | в другую БД — сначала `CREATE EXTENSION postgis`; растровые каталоги прежнего года — в `data/geodata/_removed_*` (не удалять) |
| 9 | **Подготовка чистого инстанса перед первой доставкой** | `docs/deploy-repikurr-vps.md` §3; `PIKURR/src/sqlscripts/bootstrap_empty_schema.sql` | GeoServer стартует без цикла опроса; `assessment_ready` существует | стенд/эмулятор: `REPIKURR/deploy.sh` |
| 10 | **Развёртывание сервера витрины (VPS): стек, домен, TLS, ключ доставки** | `docs/deploy-repikurr-vps.md` §1–6; `REPIKURR/docker-compose.vps.yml`, `REPIKURR/Caddyfile`, `REPIKURR/pikurr-vps-stack.service`, `REPIKURR/pikurr-watchdog.service`, `docs/round22-vps-deploy.md`; ротация паролей — §2 «Ротация паролей (порядок)» | после **любого** изменения инфраструктуры — обязательная перезагрузка ВМ и `healthcheck.py` (`deploy-repikurr-vps.md` §8, `docs/round33-reboot-incident.md`) | секреты (`.env`, `deliver.env`) не в git; пароль БД синхронно в четырёх местах (`CLAUDE.md`, «Ловушки») |
| 11 | **Выкатка фронтенда** | `REPIKURR/deploy_frontend_vps.sh` (`--check`); `docs/deploy-frontend.md`; `SS` §5.3; `CLAUDE.md` («Инструменты измерения») | скрипт сам гоняет `build_qgis_plugin.py --check`, `gen_districts_ref.py --check`, в конце — `smoke.mjs` против домена; красный прогон = ненулевой код и команда отката (`deploy_frontend_vps.sh:60-106`) | HTTP-проверка не заменяет браузерную (`CLAUDE.md`, «Ловушки») |
| 12 | **Синхронизация backend-файлов на VPS** (`deliver.py`, `healthcheck.py`, `watchdog.py`, вспомогательные) | `REPIKURR/deploy_backend_vps.sh` (`--check` по умолчанию, `--apply` — с бэкапом `.bak_pre_deploy_<TS>`, `py_compile`, перезапуск watchdog); `VPS_HOST` параметризован | `--check` сравнивает sha256 | **compose-файл, Caddyfile и `geoserver_data/` этим скриптом не сверяются** — см. расхождение в `hardware-software.md` §2 |
| 13 | **Плановое обслуживание ВМ (смена RAM и т. п.)** | `SS` §5.4; `CLAUDE.md` («Машины и доступ»); `REPIKURR/cloud-function-autostart/README.md`, «Шаг 4a» | триггер приостановлен (`yc serverless trigger pause pikurr-autostart-timer --folder-id …`) → работы → `resume` → `healthcheck.py`, `smoke.mjs` | без паузы триггера ручная остановка ВМ будет отменена в течение 5 минут |
| 14 | **Автозапуск ВМ после останова** | `REPIKURR/cloud-function-autostart/` (`main.py`, `README.md`, шаги 0–6); `docs/round42-final-technical.md` (блок C); `docs/round23-autostart-and-wfs.md`; `SS` §1, §6 | проверено фактом (round42): ~3–4 мин до `healthcheck.py` 10/10; после ручной остановки ВМ — `healthcheck.py` | триггер создан через консоль, не `yc`; интервал 5 мин (`SS` §7) |
| 15 | **Восстановление после сбоя** — ВМ остановлена посреди доставки; GeoServer завис; полная потеря ВМ | `SS` §5.5; `docs/round33-reboot-incident.md`, `docs/round41-config-decision.md`, `docs/round42-final-technical.md` (блок D) | `docker restart pikurr_vps_geoserver` (единственное известное восстановление зависания); повторная доставка подхватывается вотчдогом автоматически | зависание GeoServer — известный неисправленный механизм |
| 16 | **Резервное копирование конфигурации за пределы ВМ** | `REPIKURR/backup_config_offsite.sh` (`--restore-config-to <dir>`, `MIRROR_TO_HOST`/`MIRROR_TO_DIR`); `SS` §5.5; `docs/round43-freeze.md` (блок D) | архивы `config_*.tar.gz` (не секрет) и `secrets_*.tar.gz` (права 600) в `config_backups_offsite/` (два архива 2026-09-28 есть на координаторской); восстановление проверено на стенде (round43) | по расписанию не запускается (нет SSH-доверия стенд→VPS); секреты в git не попадают |
| 17 | **Мониторинг витрины** | `REPIKURR/external_healthcheck.sh`, `REPIKURR/systemd/pikurr-external-healthcheck.{service,timer,logrotate}`, `CLAUDE.md` («Внешний мониторинг») | лог `~/repikurr/external_healthcheck.log` на стенде (каждые 5 мин); способ уведомления (Telegram) — спроектирован, не внедрён | из вердикта исключены `db_matches_static`, `disk_space` (проверяли бы не тот хост) |
| 18 | **Проверка окна недоступности при доставке** | `REPIKURR/check_delivery_window.sh` (`BASE_URL`, `OUT`, `DURATION_S`, `POLL_INTERVAL_S`, `CURL_TIMEOUT_S`, `SLOW_THRESHOLD_S`); `CLAUDE.md` («Инструменты измерения») | лог опроса `OK/SLOW/NORESPONSE` | |
| 19 | **Очистка накопленных артефактов** (карантины `_removed_*`, `status/`, `failed/`, `backups/`) | `REPIKURR/deliver.py --cleanup [--dry-run] [--retention-days N]`; `docs/round39-cleanup.md` (блок D) | `healthcheck.py`: `disk_space` (порог 3 ГБ) | по расписанию **не запускается** (`CLAUDE.md`, «Ловушки»); каталоги карантина раунда 16 и `_removed_` не удалять без решения пользователя |
| 20 | **Сборка и выкладка плагина QGIS** | `REPIKURR/tools/build_qgis_plugin.py` (сборка `pikurr_qgis.zip` + `pikurr_qgis.sha256`, `--check`), `pikurr_qgis/metadata.txt`, `docs/round47-qgis-plugin.md`, `docs/round48-qgis-plugin.md`; выкладка — вместе с фронтендом (`public/`) | `smoke.mjs` шаги 13, 13b; `pikurr_qgis/tests/*` | справочник районов — `tools/gen_districts_ref.py [--check]` |
| 21 | **Нагрузочные замеры и ёмкость** | `REPIKURR/tools/k6_loadtest.js`, `capacity_k6.js`; `docs/round40-capacity.md`, `docs/round41-config-decision.md`; правила — `CLAUDE.md` («Правила замеров») | таблица `SS` §6 | клиент запускать на самой ВМ (`--network host`), реальный путь — через Caddy+TLS; числа стенда и VPS не смешивать |
| 22 | **Прогрев кэша GWC вручную** | `REPIKURR/tools/gwc_http_seed.py`; `docs/round35-seeding.md`, `docs/round36-seeding-fix.md`; `SS` §4 | `verify_tiles_have_data.py`; HIT-доля на `tiles_with_data.json` | автоматически прогрев выполняет `deliver.py` (`seed_gwc_cache`) |

## 2. Типовые сбои

Таблица «симптом → причина/источник → что делать → чем подтвердить» —
только ссылки на уже установленные факты (`CLAUDE.md`, «Ловушки»,
`SS` §5.5, §7; отчёты раундов).

| Симптом | Где установлено | Действие | Подтверждение |
|---|---|---|---|
| ETL: загрузка остановлена, `DownloadBanned` (401/403 от источника) | `PIKURR/src/tasks/download.py:519-522,762-765`; `PIKURR/src/utils/http_retry.py:60` | устранить причину (Referer, доступ); повторный запуск продолжит с места остановки | лог `Остановка на листе …` |
| ETL: `exportImage` отключён («FDO error»/«Failed to execute query») | `docs/incident-2026-09-10-exportimage-fdo.md`; `PIKURR/src/tasks/download.py:169-188,245-278` | продолжается через тайловый кэш, Esri, Google; повторить позже | лог «exportImage отключён до конца прогона» |
| ETL: `RuntimeError` «Требуемый провайдер … не активен» | `PIKURR/src/services/inference.py:25-33`; `docs/deploy-etl.md` | проверить драйвер/`nvidia-ctk`/`nvidia-smi`, GPU-резервирование контейнера | `docker compose run --rm etl python -c "import onnxruntime as o; print(o.get_available_providers())"` |
| ETL: непонятно, зависла ли задача (нет вывода) | `docs/deploy-etl.md` («Запуск пайплайна») | смотреть рост файлов в `outputs/predictions/…`, не считать зависанием молчание `docker logs` | число файлов растёт |
| ETL: `gaps.json`/`missing.json` | `docs/deploy-etl.md` («Склейка тайлов…»); `PIKURR/src/tasks/segmentate.py:101-117`; `PIKURR/src/tasks/download.py:586-611` | докачать тайлы, пересчитать лист (удалить `<лист>.tif` маски) | `find outputs/tiles -maxdepth 1 -name '*_gaps.json'` |
| Витрина: тайлы 400 «Unknown layer» | `CLAUDE.md` («Ловушки», GWC-эндпоинт с префиксом workspace) | слои — `pikurr:<слой>` в GWC | `healthcheck.py` (`gwc_layer[…]`), `smoke.mjs` |
| Витрина: фильтр группы не действует | `CLAUDE.md` («Ловушки», GWC игнорирует `CQL_FILTER`) | фильтры — только через `/geoserver/pikurr/wms` | шаги 3.1–3.4 `smoke.mjs` |
| Витрина: белый экран, HTTP 200 | `CLAUDE.md` («Ловушки», HTTP-проверка не исполняет JS); `docs/round33-reboot-incident.md` | браузерный `smoke.mjs`; `ErrorBoundary` | `smoke.mjs` |
| Ответ 200 с пустым телом / `ServiceExceptionReport` | `CLAUDE.md` («Ловушки», «Критерий приёмки») | проверять тело; `copy_response` в Caddy `handle_response` | `healthcheck.py` (`error_path`, `wms_getmap`, `wfs_getfeature`) |
| WMS `ServiceExceptionReport`, «Invalid date: loading» | `CLAUDE.md` («Ловушки», параметр `time`) | не передавать `time`, пока неизвестна версия данных | шаг 1 `smoke.mjs` |
| Ошибка «password authentication failed» при корректной доставке | `CLAUDE.md` («Ловушки», секрет БД); `docs/round25-secrets-and-atomicity.md`; `docs/deploy-repikurr-vps.md` («Ротация паролей») | синхронизировать пароль в `deliver.env`, роли PostgreSQL, `.env`, датасторе GeoServer | `healthcheck.py` |
| Отказ доставки «версия схемы» / «состав лет» / «усадка» | `CLAUDE.md` («Провенанс пакета…»); `docs/round26-repo-and-guards.md`, `round38-data-incident.md` | не обходить флагами без проверки пакета человеком; при законной смене — `--allow-year-change` / `--allow-shrink` | статус `step_failed`, `error` |
| «File is not a zip file» сразу после `cp` в `inbox/` | `CLAUDE.md` («Ловушки», гонка вотчдога); `docs/round39-cleanup.md` (блок C) | `mv` целой по sha256 копии обратно; отправлять через `.part` | статус доставки |
| После доставки витрина «холодная» (медленные тайлы) | `SS` §4, §7; `docs/round36-seeding-fix.md` | проверить `seed_gwc_cache` и `shortfall_warning` в статусе; при необходимости — ручной прогрев | HIT в `geowebcache-cache-result` |
| GeoServer недоступен, CPU простаивает | `CLAUDE.md` («Ловушки», очередь квоты GWC); `docs/round41-config-decision.md` | `docker restart pikurr_vps_geoserver` | `healthcheck.py` |
| Свободное место < 3 ГБ | `REPIKURR/healthcheck.py:443-469`; `docs/round39-cleanup.md` | `deliver.py --cleanup --dry-run`, затем `--cleanup` (решение оператора) | `disk_space` |
| ВМ остановлена | `SS` §5.5; README автозапуска | ждать автозапуска; если триггер забыт на паузе — `trigger resume` или запуск вручную из консоли | `healthcheck.py` |
| Поднялся не тот контейнер/лишний том | `CLAUDE.md` («Ловушки», `docker compose -f`) | всегда `-f <нужный файл>`; определить файл: `docker inspect … com.docker.compose.project.config_files` | `docker ps` |
| Контейнер не подхватил новый образ | `CLAUDE.md` («Ловушки») | `docker compose -f … up -d --force-recreate <сервис>`; для `etl` на стенде — с двумя файлами (см. следующую строку) | ID образа контейнера |
| `push` падает `rsync … code 255` | `CLAUDE.md` («Ловушки», пересоздание `etl` с override); `docs/round57-fixes.md` (дополнение о доставке) | контейнер `etl` создан только с `-f docker-compose.yml`: ключи доставки из `docker-compose.override.yml` не смонтированы (`/root/.ssh/id_rsa` — пустой каталог). Пересоздать: `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --force-recreate --no-deps etl`; отправка — `docker compose -f docker-compose.yml -f docker-compose.override.yml run --rm etl python -m src.tasks.push` | повторный `push`, статус доставки `ok: true` |
| «Остановили все контейнеры машины» | `CLAUDE.md` («Ловушки», `docker kill`/`stop`/`rm` без имени) | команды к Docker — только по имени/ID | `docker ps` |
| Стенд: nginx падает при старте (`host not found in upstream`) | `CLAUDE.md` («Ловушки», nginx.local.conf) | поднимать `geoserver` до `nginx` | доступность `/` |
| Плагин: ошибка загрузки / не совпадает архив | `pikurr_qgis/PROTOTYPE_NOTICE.md`; `docs/round47-qgis-plugin.md`; `smoke.mjs` 13/13b | пересобрать `build_qgis_plugin.py`, выкатить фронтенд | шаг 13b |

## 3. Что в эксплуатации не автоматизировано (по `CLAUDE.md`, «Открытые вопросы»)

- очистка карантинов/бэкапов/статусов на VPS (нет таймера);
- расписание `backup_config_offsite.sh` (нет SSH-доверия стенд→VPS);
- способ уведомления пользователя о сбое (Telegram — спроектирован, не внедрён);
- восстановление зависшего GeoServer (только вручную);
- запуск обработки ETL по расписанию (не предусмотрено).

## 4. Замеченные места документации, которые расходятся с фактом (не правились)

Собраны попутно при составлении указателя, для сведения:

- `docs/deploy-repikurr-vps.md` §7, строка про GeoWebCache: «сейчас GWC ни
  для одного слоя не включён» — GWC включён для двух слоёв с round32
  (`CLAUDE.md`, «Текущее состояние»; `gwc-layers` на VPS).
- `docs/deploy-etl.md`, шапка: «обучает и применяет ML-модели» — обучения в
  коде нет (`PIKURR/src/`; правило «не переобучать», `CLAUDE.md`).
- `docs/deploy-etl.md`, схема каталогов `inputs/models/two/1`,
  `onnx/two_opset13.onnx` — фактически на стенде также `one/1`
  (`ssh … find inputs/models`).
- `pikurr_qgis/PROTOTYPE_NOTICE.md`: перечисленные «известные ограничения»
  (автопоиск сервера на несуществующий домен, справочник только Витебской
  области, жёсткий `PyQt5`) устранены в 1.1.0/1.2.0 (`pikurr_qgis/metadata.txt`,
  changelog); записка не обновлена.
- `CLAUDE.md`, «Инструменты измерения»: «`smoke.mjs` … 13/13 шагов» —
  в текущем `smoke.mjs` 23 проверки с учётом подпунктов (`test-methods.md`).
- Ссылка на `docs/legacy/` — содержимое: `README.md`,
  `nginx.vps.conf.template`.
