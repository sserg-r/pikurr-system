# Схема архитектуры (round49, блок D2; round50, блок C1 — исправления)

Сырьё для будущей документации, не оформление по ГОСТ 19. Каждый узел
и стрелка — со ссылкой на раздел/файл, которым подтверждается. Ничего
сверх того, что уже описано в `docs/system-state.md` (разделы 1-2) и
конфигурации репозитория.

```mermaid
flowchart TB
    subgraph SOURCES["Внешние источники снимков (только для ETL)"]
        DZZ["dzz.by (ГП «Белгеодезия»/аналог)<br/>ArcGIS ImageServer<br/>georesursDDZ/Belarus_Web_Mercator_new<br/>приоритетный источник тайлов"]
        ESRIETL["server.arcgisonline.com (Esri)<br/>World_Imagery — запасной источник,<br/>если DZZ недоступен/низкое качество"]
        GOOGLEETL["mt1.google.com — запасной<br/>источник (та же роль, что Esri)"]
        GEE["Google Earth Engine<br/>COPERNICUS/S2_SR_HARMONIZED (Sentinel-2)<br/>+ CLOUD_SCORE_PLUS — задача usability.py"]
    end

    subgraph STAND["Стенд 192.168.251.190 (единственный источник боевых пакетов — system-state.md, п.2)"]
        ETLDB[("pikurr-system-db-1<br/>PostgreSQL/PostGIS<br/>(postgis/postgis:15-3.3)")]
        ETL["PIKURR (ETL)<br/>pikurr-system-etl-1<br/>сегментация, цветокоррекция,<br/>оценка состояния посевов"]
        PKG["PackageTask<br/>PIKURR/src/tasks/package.py<br/>-> vectors.gpkg + rasters/&lt;год&gt; + manifest.json v2.1"]
        DZZ --> ETL
        ESRIETL -. "fallback" .-> ETL
        GOOGLEETL -. "fallback" .-> ETL
        GEE --> ETL
        ETLDB --> ETL --> PKG
    end

    PKG -- "перенос в inbox/<br/>(вручную/скриптом, sha256-проверка)<br/>system-state.md п.2.4" --> INBOX

    subgraph VPS["VPS geobotany.of.by (прод, прерываемая ВМ)"]
        INBOX["inbox/"]
        WATCHDOG["watchdog.py<br/>pikurr-watchdog.service<br/>_is_stable(), защита от гонки записи"]
        DELIVER["deliver.py<br/>schema v3, манифест v2.1,<br/>SwapGuard/YearCompositionGuard,<br/>pg_dump-бэкап, REFRESH MV,<br/>прогрев GWC (z9-z12)"]
        PG[("PostGIS<br/>postgis/postgis:15-3.3<br/>agrifields/razgrafka/assessment<br/>+ assessment_ready(_latest)/levelsagg_ready")]
        GS["GeoServer 2.24.2 (kartoza)<br/>WMS/WFS/WPS + GWC<br/>gs:Query/vec:Aggregate/vec:Bounds"]
        CADDY["Caddy 2-alpine<br/>TLS-терминация, реверс-прокси,<br/>basic auth"]
        REACT["React-клиент (образ)<br/>repikurr-react:latest<br/>витрина + districts_ref.json<br/>(файл ВНУТРИ образа — обновляется<br/>только пересборкой фронтенда)"]
        STATICDIR[("./static/ на диске VPS<br/>(bind mount, НЕ в образе)<br/>year_district.json")]
        AUTOSTART["Cloud Function pikurr-autostart<br/>+ таймер (Yandex Cloud, каждые 5 минут)"]

        INBOX --> WATCHDOG --> DELIVER
        DELIVER -- "импорт, REFRESH MV" --> PG
        DELIVER -- "harvest растров,<br/>masstruncate GWC" --> GS
        DELIVER -- "пишет напрямую на диск,<br/>без пересборки фронтенда" --> STATICDIR
        GS -- "GetMap/GetFeature/WPS" --> CADDY
        REACT -- "статика (SPA)" --> CADDY
        CADDY -- "handle_path /static/* -> /srv/static<br/>(напрямую с диска, Caddyfile)" --> STATICDIR
        CADDY -- "handle {} -> react-client:80<br/>(всё остальное, включая districts_ref.json)" --> REACT
        CADDY -- "https://geobotany.of.by" --> USER_BROWSER
        AUTOSTART -. "проверяет каждые 5 минут,<br/>поднимает ВМ если STOPPED" .-> VPS
    end

    VPS -. "облако принудительно останавливает<br/>прерываемую ВМ раз в ≤24ч<br/>(не связано с частотой триггера)" .-> AUTOSTART

    USER_BROWSER["Браузер пользователя<br/>(витрина)<br/>подложки: OSM, Esri World_Imagery"]

    subgraph DESKTOP["Рабочее место пользователя (произвольная машина)"]
        QGISPLUGIN["Плагин pikurr 1.2.0<br/>QDockWidget-панель<br/>QgsBlockingNetworkRequest<br/>подложки: OSM, Esri World_Imagery"]
    end

    QGISPLUGIN -- "WPS (gs:Query/vec:Aggregate/vec:Bounds),<br/>WMS (слой полей), WMTS (AI-оценка через GWC)" --> CADDY
    QGISPLUGIN -. "districts_ref.json<br/>(через react-client — ещё не задеплоен,<br/>round47/48/49/50)" .-> CADDY
    CADDY -. "/static/year_district.json<br/>(читает список лет, round48 C2.1)" .-> QGISPLUGIN

    subgraph COORD["Координаторская машина (эта сессия)"]
        REPO[("Git-репозиторий<br/>github.com/sserg-r/pikurr-system")]
        BUILD["build_qgis_plugin.py /<br/>gen_districts_ref.py<br/>(--check в deploy_frontend_vps.sh,<br/>round49 A7)"]
        DEPLOY["deploy_frontend_vps.sh<br/>реальный порядок (round50, C1.2):<br/>build -> перенос образа (save/scp/load)<br/>-> force-recreate (прод переключён!)<br/>-> smoke.mjs (проверка ПОСЛЕ)"]
        REPO --> BUILD --> DEPLOY -.-> VPS
    end

    style ETLDB fill:#f9d5d5
    style PG fill:#d5e8f9
    style GS fill:#d5f9d8
    style CADDY fill:#f9f3d5
    style STATICDIR fill:#e8d5f9
```

## Пояснения к узлам (со ссылками)

| Узел на схеме | Подтверждается | Раздел/файл |
|---|---|---|
| `pikurr-system-db-1` | единственный правильный источник боевых пакетов | `docs/system-state.md`, п.2.2; `CLAUDE.md`, инцидент round38 |
| `PIKURR (ETL)` / `PackageTask` | состав, манифест v2.1, `etl_git_commit` | `docs/system-state.md`, п.1-2 |
| `dzz.by` (приоритетный источник) | `PIKURR/src/tasks/download.py::_fetch_dzz_tile_cache/_fetch_dzz_export_tile`, порядок `sources` (строки ~496-513): DZZ первым, Esri/Google — fallback при недоступности/низком качестве (`passes_quality()`, не менялось) | `PIKURR/.env.example` (`TILESERVICES__DZZ`), `PIKURR/configs.ini` |
| `server.arcgisonline.com` / `mt1.google.com` (ETL, fallback) | та же логика `sources`, роль — запасной источник, не основной | `PIKURR/src/tasks/download.py`, комментарий "Esri и Google — без Referer (см. ТЗ 1.1)" |
| `Google Earth Engine` | используется в `PIKURR/src/tasks/usability.py` через `PIKURR/src/services/gee.py` (`COPERNICUS/S2_SR_HARMONIZED`, `GOOGLE/CLOUD_SCORE_PLUS`) — точная роль внутри задачи usability не анализировалась (вне объёма, не модель/сегментация) | `PIKURR/src/services/gee.py` |
| `watchdog.py` | защита от гонки записи, работает на VPS и стенде | `CLAUDE.md`, "Ловушки", round38/39 |
| `deliver.py` | schema v3, предохранители D1-D4, прогрев GWC z9-z12 | `docs/system-state.md`, п.2.5, "Текущее состояние системы" |
| `PostGIS`/`GeoServer`/`Caddy` | версии образов | `REPIKURR/docker-compose.vps.yml`; `docs/third-party-components.md` |
| `./static/` (bind mount) — `year_district.json` | **живёт на диске VPS, НЕ в образе** — `deliver.py` пишет его напрямую при каждой доставке; Caddy отдаёт из `/srv/static` (`handle_path /static/*`), минуя react-client | `REPIKURR/Caddyfile` (строки 68-69), `REPIKURR/docker-compose.vps.yml` (`./static:/srv/static:ro`) — round50, C1.4 |
| `react-client` (образ) — `districts_ref.json` | **внутри образа фронтенда** (`public/districts_ref.json`, копируется при `docker build`) — обновляется ТОЛЬКО пересборкой/передеплоем фронтенда, не отдельно; Caddy отдаёт через catch-all `handle {}` → `reverse_proxy react-client:80` | `REPIKURR/Caddyfile` (строка 181-183) — round50, C1.4 |
| `Cloud Function pikurr-autostart` | триггер срабатывает **каждые 5 минут** (проверяет и поднимает, если ВМ `STOPPED`) — это ОТДЕЛЬНЫЙ факт от того, что облако принудительно останавливает прерываемую ВМ **раз в ≤24ч** (round50, C1.1: round49/round42 смешивали эти две цифры в одной подписи) | `docs/system-state.md`, строки ~53, ~155, ~188; `docs/round42-final-technical.md`, блок C |
| Плагин QGIS → Caddy (WMS/WPS/WMTS) | пути запросов плагина | `pikurr_qgis/pikurr.py::_update_fields_layer/_add_raster_layer`; `docs/round48-qgis-plugin.md` |
| Плагин QGIS ⇢ `districts_ref.json` | ещё не задеплоен на прод (пунктир) — раз он живёт в образе react-client, появится только со следующим деплоем фронтенда | `docs/round47-addendum-districts-ref-not-deployed.md` |
| `build_qgis_plugin.py`/`gen_districts_ref.py` → `deploy_frontend_vps.sh` | проверка дрейфа ДО `docker build` | `REPIKURR/deploy_frontend_vps.sh` (round49, A7) |
| `deploy_frontend_vps.sh` — реальный порядок | **`smoke.mjs` идёт ПОСЛЕ `force-recreate`, не до** — прод уже переключён на новый образ к моменту проверки; откат при красном прогоне — ручной (команда печатается скриптом, не выполняется автоматически). round50, C1.2: раньше схема показывала "build → smoke → force-recreate", что не соответствовало коду | `REPIKURR/deploy_frontend_vps.sh`, строки 77 (build) → 80-93 (перенос образа, retag, force-recreate) → 101 (smoke.mjs) |

## Важное ограничение, отражённое схемой (round50, C1.2)

Правило CLAUDE.md «не выкатывать фронтенд без зелёного `smoke.mjs`» на
практике реализовано как «не **считать выкатку завершённой** без
зелёного `smoke.mjs`», а не как гейт ДО переключения прода — код
`deploy_frontend_vps.sh` физически не может проверить образ до того,
как он окажется на VPS и заменит текущий контейнер (`force-recreate`).
Разница существенна: в окне между `force-recreate` и завершением
`smoke.mjs` прод уже обслуживает новый (непроверенный) образ. Это не
новая находка этого раунда — так было устроено с round35 — но текстовое
описание схемы раньше подразумевало обратный порядок.

## Что намеренно не включено

- Внутреннее устройство CV-модели (сегментация, цветокоррекция) — вне
  рамок документа, "Не делать" во всех раундах с плагином QGIS.
- Разработческий стенд `192.168.251.190` показан только как источник
  ETL-пакетов — его роль "площадки для экспериментов, которые нельзя
  ставить на прод" (`CLAUDE.md`, "Машины и доступ") на схему не
  выведена отдельно, чтобы не усложнять диаграмму содержанием, не
  относящимся к потоку данных пакета.
- Локальный стек `docker-compose.local.yml` на координаторской машине
  (`pikurr_local_*`, обнаружен при инвентаризации инцидента round48,
  см. `docs/round49-autonomous.md`, блок 0) — не описан нигде в
  `system-state.md` и не является частью боевого или тестового контура
  по актуальному описанию системы; не включён в схему как узел с
  неясным назначением без факта о его текущей роли (открытый вопрос
  пользователю, round49/50).
