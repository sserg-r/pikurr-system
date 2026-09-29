# Сторонние компоненты — сводка (round49, блок D1; round50, блок C2 — дополнения)

Сырьё для будущей документации, не оформление по ГОСТ 19. Источник
каждой строки указан явно — только чтение, ничего не устанавливалось
заново специально для этого списка. Условия использования внешних
сервисов не интерпретируются как юридический вывод — только факты и
ссылки (round50, "Не делать").

## Прод (VPS), контейнеры

| Компонент | Версия (тег образа) | Лицензия | Где используется | Источник версии |
|---|---|---|---|---|
| PostGIS (на базе PostgreSQL) | `postgis/postgis:15-3.3` (PostgreSQL 15, PostGIS 3.3) | PostgreSQL: PostgreSQL License (permissive, BSD-подобная); PostGIS: GPL-2.0-or-later | Хранилище данных витрины (`agrifields`, `razgrafka`, `assessment`) | `REPIKURR/docker-compose.vps.yml`, тег образа |
| GeoServer (образ kartoza) | `kartoza/geoserver:2.24.2` | GeoServer: GPL-2.0-or-later (ядро) + отдельные лицензии части расширений (WPS — тот же GPL-2.0); образ kartoza — отдельная лицензия сборки (не проверялась) | WMS/WFS/WPS/GWC — вся отдача геоданных | `REPIKURR/docker-compose.vps.yml` |
| Caddy | `caddy:2-alpine` | Apache-2.0 | Реверс-прокси, TLS-терминация, basic auth | `REPIKURR/docker-compose.vps.yml` |
| React-клиент (свой образ) | `repikurr-react:latest` (собственная сборка) | — (собственный код) | Фронтенд-контейнер (nginx + собранный React) | `REPIKURR/docker-compose.vps.yml`; версия — не тег, а дата сборки (`deploy_frontend_vps.sh`, `TAG=round_deploy_<TS>`) |
| ├─ базовый образ (сборка) | `node:20-alpine` | MIT (Node.js) | Только этап сборки (`npm run build`) — не попадает в финальный образ | `REPIKURR/repikurr/Dockerfile`, этап 1 (round50, C2.3) |
| ├─ базовый образ (раздача) | `nginx:alpine` → **nginx/1.29.8** (версия внутри образа на 2026-09-29, тег плавающий, не запинен) | BSD-2-Clause (nginx) | Раздача собранного React SPA | `REPIKURR/repikurr/Dockerfile`, этап 2; версия — `docker run --rm nginx:alpine nginx -v` (round50, C2.3) |

## Фронтенд (npm, `REPIKURR/repikurr/package-lock.json`)

| Компонент | Версия (точная, из lock-файла) | Лицензия | Где используется | Источник |
|---|---|---|---|---|
| React | 19.1.1 | MIT | UI фреймворк витрины | `package-lock.json` |
| React DOM | 19.1.1 | MIT | рендеринг React | `package-lock.json` |
| React Leaflet | 5.0.0 | **Hippocratic-2.1** (не классический open-source — этическая лицензия с ограничениями по неправомерному использованию; требует отдельного юридического рассмотрения для документации) | обёртка Leaflet для React (карта) | `package-lock.json` |
| @react-leaflet/core | 3.0.0 | **Hippocratic-2.1** (та же лицензия, что React Leaflet — round50, C2.5) | внутренняя зависимость React Leaflet, отдельно не используется напрямую | `package-lock.json` |
| Leaflet | 1.9.4 | BSD-2-Clause | карта, тайловые слои | `package-lock.json` |
| Leaflet.wms | 0.2.0 | MIT | WMS-слои на карте | `package-lock.json` |
| esri-leaflet | 3.0.18 | Apache-2.0 | подложка Esri (см. отдельный список ниже) | `package-lock.json` |
| react-icons | 5.6.0 | MIT (сам пакет; иконки внутри — из разных icon-наборов, каждый со своей лицензией — не сверялось построчно) | иконки интерфейса | `node_modules/react-icons/package.json` |
| Vite | 7.1.3 | MIT | сборщик фронтенда | `package-lock.json` |

## Инструменты замеров/проверки (не поставляются на прод)

| Компонент | Версия | Лицензия | Где используется | Источник |
|---|---|---|---|---|
| Playwright | 1.63.0 | Apache-2.0 | `smoke.mjs` — дымовой сценарий браузера | `REPIKURR/tools/smoke/package-lock.json` |
| k6 (Grafana) | **2.3.0** (по факту версии внутри тега `grafana/k6:latest` на 2026-09-29, `k6 version`) | AGPL-3.0 (сам k6) | нагрузочные тесты (`k6_loadtest.js`, `capacity_k6.js`) | round50, C3.1: ни в одном файле репозитория (`.sh`, `.md`, `.js`) не нашлось сохранённой команды `docker run .../k6:latest` — команды запуска вводились вручную операторами в прошлых раундах и не сохранялись как скрипт, поэтому "запинить версию в командах" технически некуда применить. Рекомендация на будущее: если/когда появится постоянный скрипт запуска k6, указывать в нём тег `grafana/k6:2.3.0`, не `:latest`. |

## Плагин QGIS

| Компонент | Версия | Лицензия | Источник |
|---|---|---|---|
| Сам плагин `pikurr` | 1.2.0 | GPL-2.0-or-later (шапка `pikurr.py`: "under the terms of the GNU General Public License ... either version 2") | `pikurr_qgis/metadata.txt`, `pikurr_qgis/pikurr.py` |
| QGIS (минимальная поддерживаемая версия) | 3.44 | GPL-2.0-or-later (ядро QGIS) | `pikurr_qgis/metadata.txt`; факт проверки — round48/49, нативная установка на координаторской машине (Docker-образы `qgis/qgis` не удалось прогнать технически, см. `docs/round48-qgis-plugin.md` A6.3 и этот отчёт, блок C) |

## ETL-контур — фактические версии (round50, C2.2)

`requirements.txt` не фиксирует версии большинства пакетов — раньше
раздел был ограничен этим списком без версий. round50 прочитал
**фактически установленные версии** прямо в работающем контейнере на
стенде (только чтение, ничего не менялось/не запускалось):
```
ssh 192.168.251.190 "docker exec pikurr-system-etl-1 pip list --format=freeze"
```
Чтение не было заблокировано классификатором.

| Пакет | Версия (факт, контейнер стенда) | Лицензия |
|---|---|---|
| numpy | 2.5.3 | BSD-3-Clause |
| pandas | 3.0.5 | BSD-3-Clause |
| rasterio | 1.5.1 | BSD-3-Clause |
| shapely | 2.1.2 | BSD License (OSI) |
| scikit-image | 0.26.0 | BSD License (OSI) |
| psycopg2-binary | 2.9.13 | LGPL (OSI) |
| pillow (Pillow) | 12.3.0 | MIT-CMU |
| streamlit | 1.63.0 | Apache-2.0 |
| sqlalchemy | 2.0.53 | MIT |
| tenacity | 9.1.4 | Apache-2.0 |
| google-auth | 2.58.0 | Apache-2.0 |
| earthengine-api | 1.7.43 | Apache-2.0 (OSI) |
| pydantic / pydantic-settings | 2.13.5 / 2.15.0 | (не сверялось отдельно) |
| python-dotenv | 1.2.3 | (не сверялось отдельно) |
| **onnxruntime-gpu** | **1.26.0** (совпадает с зафиксированной в `requirements.txt`) | **MIT** (round50, C2.3) |

Полный список (`pip list --format=freeze`, ~70 пакетов) — не
переносился построчно, приведены пакеты, явно упомянутые в
`requirements.txt`/использующиеся в коде ETL, плюс `onnxruntime-gpu`.

## Входные данные ETL — сторонние сервисы снимков (round50, C2.1)

Установлено по коду (`PIKURR/src/tasks/download.py`,
`PIKURR/src/services/gee.py`, `PIKURR/.env.example`,
`PIKURR/configs.ini`) — только адреса и роль, условия использования не
интерпретировались.

| Сервис | Точный адрес | Способ доступа | Роль (по коду) |
|---|---|---|---|
| dzz.by | `https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_Web_Mercator_new/ImageServer/tile/{z-6}/{y}/{x}` (плюс альтернативный вариант через `Java/proxy.jsp`, закомментирован в `configs.ini`) | ArcGIS ImageServer, тайлы | **Приоритетный** источник снимков для ETL (`download.py`, порядок `sources`: dzz — первый, если `dzz_cfg.prefer_export` — через export-эндпоинт, иначе через кэш тайлов) |
| server.arcgisonline.com (Esri) | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | ArcGIS MapServer, тайлы | **Запасной** источник для ETL, если dzz недоступен или тайл не прошёл `passes_quality()` (не менялось); также подложка на витрине и в плагине QGIS (`esri-leaflet`/прямой XYZ) |
| mt1.google.com (Google) | `https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}` | Google Maps tile API (незадокументированный публичный эндпоинт) | Тот же запасной уровень, что Esri, для ETL — `download.py`, комментарий "Esri и Google — без Referer (см. ТЗ 1.1)" |
| Google Earth Engine | `COPERNICUS/S2_SR_HARMONIZED` (Sentinel-2), `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` | Earth Engine Python API (`earthengine-api`), OAuth (`googleapis.com/auth/earthengine`) | Используется в задаче `PIKURR/src/tasks/usability.py` через `PIKURR/src/services/gee.py` — точная роль внутри самой задачи (usability/пригодность участков) не анализировалась дальше (не модель/сегментация, но и не тривиальный факт для одной строки таблицы) |

Официальные страницы условий использования (ссылки, не интерпретация):
Esri World Imagery — часть ArcGIS Online, условия у Esri (правообладатель
сервиса); Google Maps tile API — не публичный документированный API
(используется как есть, без официального SDK); Google Earth Engine —
условия Google Earth Engine (некоммерческое/коммерческое использование
разграничено самим Google); dzz.by — точный правообладатель и условия использования по коду и
репозиторию **не устанавливаются**, нужна отдельная проверка
непосредственно у оператора сервиса.

## Веса моделей (round50, C2.4)

По репозиторию **не устанавливается**, использовались ли предобученные
веса/бэкбоны сторонних авторов (ImageNet и т.п.):
- `PIKURR/models/models.config` описывает две TensorFlow Serving модели
  (`one`, `two`) без опознаваемых по имени меток архитектуры/источника
  весов.
- Поиск по коду (`grep -rn "backbone|pretrained|ImageNet|resnet|
  efficientnet|mobilenet" PIKURR/src/`) не дал совпадений.
- Сами файлы весов не читались и не анализировались (бинарные,
  содержательный анализ потребовал бы загрузки в фреймворк — то есть
  фактического запуска модели, что прямо запрещено этим и предыдущими
  раундами).

Итог: **не установлено** — ни подтвердить, ни опровергнуть использование
сторонних предобученных весов по доступным средствам этого раунда.

## Внешние сервисы данных (подложки) — вопрос для документов, не решение

- **OpenStreetMap** (`tile.openstreetmap.de`) — карта используется как
  базовая подложка (плагин и витрина). Условия использования тайлового
  сервера OSM ограничивают интенсивность запросов и требуют указания
  авторства — авторство на витрине уже выводится (round33,
  `CLAUDE.md`: "атрибуция карты — только сторонние источники"),
  формальное соглашение с OSM Foundation (если требуется для
  промышленной эксплуатации) не заключалось, это вопрос для
  документов/юристов, не для этого раунда.
- **Esri World Imagery** (`server.arcgisonline.com`) — используется как
  спутниковая подложка (эталонный слой "Esri"), через публичный
  бесплатный эндпоинт `esri-leaflet`. Условия использования у Esri для
  промышленного применения (не для ознакомительного использования)
  обычно требуют лицензии ArcGIS — **не проверялось и не оформлялось**,
  это открытый вопрос для документов и для пользователя: требуется ли
  отдельная лицензия Esri для того объёма использования, который есть
  у системы сейчас.

## Не удалось установить фактом

- Лицензия образа `kartoza/geoserver` как сборки (сам GeoServer —
  GPL-2.0, но скрипты/обвязка Docker-образа kartoza могут иметь
  отдельные условия — не проверено, LICENSE-файл образа не сверялся).
- Построчная сверка лицензий транзитивных npm-зависимостей (только
  верхнеуровневые пакеты из `dependencies`/`devDependencies` сверены
  явно).
