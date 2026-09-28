# Схема архитектуры (round49, блок D2)

Сырьё для будущей документации, не оформление по ГОСТ 19. Каждый узел
и стрелка — со ссылкой на раздел/файл, которым подтверждается. Ничего
сверх того, что уже описано в `docs/system-state.md` (разделы 1-2) и
конфигурации репозитория.

```mermaid
flowchart TB
    subgraph STAND["Стенд 192.168.251.190 (единственный источник боевых пакетов — system-state.md, п.2)"]
        ETLDB[("pikurr-system-db-1<br/>PostgreSQL/PostGIS<br/>(postgis/postgis:15-3.3)")]
        ETL["PIKURR (ETL)<br/>pikurr-system-etl-1<br/>сегментация, цветокоррекция,<br/>оценка состояния посевов"]
        PKG["PackageTask<br/>PIKURR/src/tasks/package.py<br/>-> vectors.gpkg + rasters/&lt;год&gt; + manifest.json v2.1"]
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
        REACT["React-клиент<br/>repikurr-react:latest<br/>витрина (Leaflet, WMS/WFS/WMTS)"]
        YEARJSON["static/year_district.json<br/>(источник правды год/район<br/>для фронтенда И плагина QGIS)"]
        AUTOSTART["Cloud Function pikurr-autostart<br/>+ таймер (Yandex Cloud)<br/>запускает ВМ, если STOPPED"]

        INBOX --> WATCHDOG --> DELIVER
        DELIVER -- "импорт, REFRESH MV" --> PG
        DELIVER -- "harvest растров,<br/>masstruncate GWC" --> GS
        DELIVER -- "пишет" --> YEARJSON
        GS -- "GetMap/GetFeature/WPS" --> CADDY
        REACT -- "статика (SPA)" --> CADDY
        CADDY -- "https://geobotany.of.by" --> USER_BROWSER
        YEARJSON -. "читает списки года/района" .-> REACT
        AUTOSTART -. "поднимает ВМ,<br/>если остановлена<br/>(раз в ≤24ч)" .-> VPS
    end

    USER_BROWSER["Браузер пользователя<br/>(витрина)"]

    subgraph DESKTOP["Рабочее место пользователя (произвольная машина)"]
        QGISPLUGIN["Плагин pikurr 1.2.0<br/>QDockWidget-панель<br/>QgsBlockingNetworkRequest"]
    end

    QGISPLUGIN -- "WPS (gs:Query/vec:Aggregate/vec:Bounds),<br/>WMS (слой полей), WMTS (AI-оценка через GWC)" --> CADDY
    QGISPLUGIN -. "districts_ref.json<br/>(генерируется из constants.js,<br/>ещё не задеплоен — round47/48/49)" .-> CADDY
    YEARJSON -. "читает список лет<br/>(round48, C2.1)" .-> QGISPLUGIN

    subgraph COORD["Координаторская машина (эта сессия)"]
        REPO[("Git-репозиторий<br/>github.com/sserg-r/pikurr-system")]
        BUILD["build_qgis_plugin.py /<br/>gen_districts_ref.py<br/>(--check в deploy_frontend_vps.sh,<br/>round49 A7)"]
        DEPLOY["deploy_frontend_vps.sh<br/>build -> smoke.mjs -> force-recreate"]
        REPO --> BUILD --> DEPLOY -.-> VPS
    end

    style ETLDB fill:#f9d5d5
    style PG fill:#d5e8f9
    style GS fill:#d5f9d8
    style CADDY fill:#f9f3d5
```

## Пояснения к узлам (со ссылками)

| Узел на схеме | Подтверждается | Раздел/файл |
|---|---|---|
| `pikurr-system-db-1` | единственный правильный источник боевых пакетов | `docs/system-state.md`, п.2.2; `CLAUDE.md`, инцидент round38 |
| `PIKURR (ETL)` / `PackageTask` | состав, манифест v2.1, `etl_git_commit` | `docs/system-state.md`, п.1-2 |
| `watchdog.py` | защита от гонки записи, работает на VPS и стенде | `CLAUDE.md`, "Ловушки", round38/39 |
| `deliver.py` | schema v3, предохранители D1-D4, прогрев GWC z9-z12 | `docs/system-state.md`, п.2.5, "Текущее состояние системы" |
| `PostGIS`/`GeoServer`/`Caddy` | версии образов | `REPIKURR/docker-compose.vps.yml`; `docs/third-party-components.md` |
| `static/year_district.json` | единый источник списка год/район для витрины И плагина | `docs/system-state.md`, п.2.6; `pikurr_qgis/geoserver_client.py::fetch_year_district_data` (round48, C2.1) |
| `Cloud Function pikurr-autostart` | развёрнуто и проверено фактом | `docs/round42-final-technical.md`, блок C |
| Плагин QGIS → Caddy (WMS/WPS/WMTS) | пути запросов плагина | `pikurr_qgis/pikurr.py::_update_fields_layer/_add_raster_layer`; `docs/round48-qgis-plugin.md` |
| Плагин QGIS ⇢ `districts_ref.json` | ещё не задеплоен на прод (пунктир) | `docs/round47-addendum-districts-ref-not-deployed.md` |
| `build_qgis_plugin.py`/`gen_districts_ref.py` → `deploy_frontend_vps.sh` | проверка дрейфа ДО `docker build` | `REPIKURR/deploy_frontend_vps.sh` (round49, A7) |

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
  см. отчёт этого раунда, блок 0) — не описан нигде в `system-state.md`
  и не является частью боевого или тестового контура по актуальному
  описанию системы; не включён в схему как непонятный по назначению
  узел без факта о его текущей роли.
