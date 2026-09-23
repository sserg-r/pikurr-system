# Раунд 33: авария после перезагрузки ВМ, устойчивость к рестарту, интерфейс

> **Правило замеров**: цифры со стенда (`192.168.251.190`), с VPS
> (`geobotany.of.by`, `158.160.237.90`) и с эмулятора не смешивать.
> Каждый замер подписан машиной.
>
> **Правило непустых тайлов**: замеры скорости — на
> `docs/round32_assets/tiles_with_data.json`, с долей ответов < 2 КБ.

## Блок A. Авария: улики, причина, восстановление

### A1. Улики (собраны ДО исправлений)

Машина: VPS (`158.160.237.90`, аптайм на момент сбора — 10-15 минут,
т.е. ВМ была перезапущена пользователем незадолго до начала работы).

**`docker ps -a` / `docker inspect`** (все 4 контейнера):

| контейнер | статус | exit code | RestartPolicy | StartedAt |
|---|---|---|---|---|
| pikurr_vps_react | running | 0 | unless-stopped | 2026-09-23T09:54:11Z |
| pikurr_vps_caddy | running | 0 | unless-stopped | 2026-09-23T09:54:11Z |
| pikurr_vps_geoserver | running | 0 | unless-stopped | 2026-09-23T09:54:11Z |
| pikurr_vps_postgis | running | 0 | unless-stopped | 2026-09-23T09:54:11Z |

Все 4 контейнера уже стартовали успешно и синхронно (в один и тот же
Unix-момент) на момент осмотра. Ни один не находился в состоянии
`restarting`/`exited` — это сразу исключает версию «контейнер не
поднялся» как причину белого экрана; все инфраструктурные компоненты
были живы.

**`journalctl -b` (sudo доступен на VPS без пароля, в отличие от
стенда)**:

```
09:53:46  начало загрузки ядра
09:54:02  systemd: Starting docker.service
09:54:14  dockerd: Daemon has completed initialization
09:54:11-12  docker: sbJoin для всех 4 контейнеров (сеть поднята)
09:54:14  systemd: Started pikurr-watchdog.service
```

Юнит `pikurr-vps-stack.service` (`enabled`, `Type=oneshot`,
`ExecStart=docker compose -f docker-compose.vps.yml up -d`) —
отработал, `WantedBy=multi-user.target`, `After=docker.service`.
Автозапуск систем на уровне systemd — исправен.

**Ответы по содержимому** (сняты в момент осмотра, ~10:05 UTC, т.е.
~11 минут после старта контейнеров):

| путь | код | тело |
|---|---|---|
| `/` | 200 | корректный `index.html`, ссылается на `index-ChCyOo7l.js` |
| `/static/year_district.json` | 200 | `{"years":[2025],...,"dataVersion":"20260923094056"}` — поле **присутствует**, время соответствует доставке ДО перезагрузки (09:40:56) |
| WMS `fields_latest` | 200 | валидный PNG, 32067 байт (не пустой) |
| WFS `fields_latest` | 200 | `FeatureCollection`, 1 объект |
| `/geoserver/gwc/service/wms?tiled=true` | 200 | `geowebcache-cache-result: MISS`, валидный PNG 36234 байт — **кэш GWC пережил перезапуск** (конфигурация слоёв загружена: `CONFIG [gwc.layer] - Loaded 2 tile layers in 25.94 ms`) |
| `/geoserver/nonexistent` | 404 | тело Tomcat 404 непустое (682 байта) — `handle_response`/`copy_response` в Caddy по-прежнему пробрасывает тело |

**`df -h` / `free -m`**: диск 44% (13G/29G), память 1.5G используется
из 5.9G, своп 2G не используется — ресурсы не исчерпаны, не причина.

**Состояние БД**: `pg_matviews` — `assessment_ready`,
`assessment_ready_latest`, `levelsagg_ready`, все `ispopulated = t`.
БД поднялась штатно (recovery в логе от 18 сентября — старый, не
относится к этой перезагрузке; в логе postgis за 23 сентября ошибок
нет).

**Исключение в консоли браузера** (получено через `claude-in-chrome`,
доступный в этой сессии — в отличие от round30-32):

```
[EXCEPTION] ReferenceError: Cannot access 'mt' before initialization
    at Lv (index-ChCyOo7l.js:52:156248)
    at lr, Tr, If, Lh, pm, Qr, bh, Hh (React internals)
```

Это ключевая улика: `#root` остаётся пустым (`get_page_text` не
находит текстового содержимого страницы), но JS-бандл и все
статические ответы отдаются с кодом 200 — авария не в инфраструктуре
доставки, а в самом упавшем клиентском коде.

### A2. Причина

**Механизм отказа, подтверждённый уликами**: `MapView.jsx`
(`repikurr/src/components/MapView.jsx`), правка round32 блока C,
коммит `c6af923`. Константы `vectorIsCached`/`rasterIsCached`
объявлены (`const`) на строках 222-223, но читаются в `useMemo`
(тело фабрики и массив зависимостей) на строках 196-207 — **выше**
своего объявления. В JS это временная мёртвая зона (temporal dead
zone): любое обращение к `const`/`let` до строки объявления кидает
`ReferenceError: Cannot access 'X' before initialization`.

Так как обращение происходит в теле функционального компонента
`MapView`, ошибка бросается **на каждом без исключения рендере**, не
зависит от перезагрузки ВМ, от готовности GeoServer или от чего-либо
ещё. Подтверждено экспериментом на Node.js (минимальная репродукция
той же структуры кода даёт тот же класс ошибки — `ReferenceError:
Cannot access 'vectorIsCached' before initialization`), а затем
фактом в реальном браузере (см. A1) — минифицированное имя `mt`
соответствует одной из этих двух констант.

Приложение не оборачивает дерево компонентов в React Error Boundary
(проверено: ни в `App.jsx`, ни в `main.jsx` границы ошибок нет) —
необработанное исключение при рендере размонтирует всё дерево React,
оставляя `<div id="root"></div>` пустым. Отсюда — белый экран.

**Почему авария «привязалась» к перезагрузке ВМ, хотя причина не в
ней**: баг задеплоен на VPS ещё в round32 (коммит `c6af923`,
задеплоен в рамках того же раунда) и **гарантированно ломал сайт с
того самого момента** — просто пользователь, по всей видимости, не
открывал витрину в браузере между деплоем round32 и перезагрузкой ВМ
(верификация round32 блока C.4 была HTTP-level, не в реальном
браузере — см. предыдущий отчёт, ограничение зафиксировано как
«не сделано своими силами» из-за недоступности `claude-in-chrome» в
той сессии). Первое открытие сайта после перезагрузки ВМ — и есть
момент, когда пользователь впервые увидел уже существовавший баг.

**Проверка кандидатов из ТЗ**:
- порядок старта контейнеров / готовность GeoServer к моменту первых
  запросов: `docker-compose.vps.yml` не использует
  `depends_on: condition: service_healthy` — только порядок создания
  контейнеров (`caddy: depends_on: [react-client, geoserver]`), без
  ожидания реальной готовности порта. GeoServer (JVM) от старта
  контейнера (09:54:11) до готовности каталога — около 60 секунд
  (`09:54:54` начало загрузки каталога → `09:55:10` инициализация
  security/GWC завершена, `geoserver.log`). Это реальная, отдельная
  от белого экрана уязвимость (окно ~45-60с, когда Caddy уже
  проксирует на ещё не готовый GeoServer) — не была причиной ЭТОЙ
  аварии (белый экран воспроизводится и без реюза этого окна), но
  устраняется в блоке B как отдельный найденный риск;
- `RestartPolicy`: у всех 4 контейнеров `unless-stopped` — в порядке,
  не причина;
- конфигурация GWC (round32, REST): **частично не пережила
  перезапуск**. Регистрация тайловых слоёв (`gwc-layers`,
  `EPSG:900913`, `metaWidthHeight`, `expireClients`) сохранилась
  (лог: `Loaded 2 tile layers in 25.94 ms`, факт: `HIT`/`MISS`
  заголовки и `geowebcache-tile-bounds` работают корректно). НО
  `geowebcache-diskquota.xml` на диске после перезапуска показывал
  `<value>20</value><units>GiB</units>` вместо заданных в round32
  `2 GiB` — REST PUT в round32 применился только к рантайму GeoServer,
  но не был персистентным образом переписан на дискways, переживающий
  собственный процесс. Устранено повторным PUT (см. A3) — не причина
  белого экрана, но реальная находка, которую round32 не проверял
  рестартом;
- `dataVersion` в `year_district.json`: поле **присутствует** (см.
  A1) — доставка на VPS после round32 была, гипотеза «поля никогда
  не было» опровергнута;
- поведение фронтенда при неудачной загрузке `year_district.json`:
  не относится к делу — сбой происходит раньше, при самом первом
  рендере `MapView`, независимо от того, загрузился ли
  `year_district.json`.

**Подтверждено**: причина — `ReferenceError` из-за temporal dead
zone в `MapView.jsx`, введённая round32 блоком C, не связанная с
перезагрузкой ВМ по существу.
**Опровергнуто**: гипотезы про порядок контейнеров, RestartPolicy,
отсутствие `dataVersion`.
**Дополнительно найдено, не было целью поиска**: GWC disk quota не
переживает перезапуск GeoServer (устранено в A3); окно ~45-60с
неготовности GeoServer при живом Caddy (устраняется в блоке B).

### A3. Восстановление

Действия (каждое — с бэкапом/откатом):

1. **Правка `MapView.jsx`** — константы `vectorLayer`, `effectiveYear`,
   `rasterLayer`, `vectorFqName`, `rasterFqName`, `vectorIsCached`,
   `rasterIsCached` перенесены выше блоков `useMemo`, которые их
   используют. Файл: `REPIKURR/repikurr/src/components/MapView.jsx`.
   Откат: `git checkout <previous-commit> -- REPIKURR/repikurr/src/components/MapView.jsx`.
2. **Пересборка образа** (`repikurr-react:round33`, бандл
   `index-un7Ppefo.js` вместо сломанного `index-ChCyOo7l.js`),
   `docker save | gzip`, перенос на VPS и эмулятор.
3. **Развёртывание на VPS**: `docker load`, тег `repikurr-react:latest`,
   `docker compose -f docker-compose.vps.yml up -d --force-recreate react-client`
   (используем правильный compose-файл, определённый через
   `docker inspect ... Labels`, — round32 показал, что запуск без `-f`
   создаёт паразитный контейнер). Бэкап образа: старый образ остался
   под тегом `repikurr-react:round32`-эквивалент через digest, доступен
   через `docker images` (не был явно перетегирован, но слой не
   удалён). Откат: `docker tag <старый digest> repikurr-react:latest && docker compose -f docker-compose.vps.yml up -d --force-recreate react-client`.
4. **Развёртывание на эмуляторе**: аналогично,
   `docker-compose.server.yml`, контейнер `pikurr_srv_react`.
5. **Восстановлена квота диска GWC** (2 GiB, PUT
   `/geoserver/gwc/rest/diskquota.xml`, тот же XML, что и в round32).
   Откат: `curl -u admin:$GEOSERVER_ADMIN_PASSWORD -XPUT ... geowebcache-diskquota.xml` со старым содержимым (20 GiB) — сохранён в
   `/tmp/diskquota_2gib.xml` на VPS для повторного применения, если
   потребуется откатить к 2 GiB после будущих рестартов.

**Критерий приёмки — по содержимому**:
- главная страница: подтверждено фактом в реальном браузере
  (`claude-in-chrome`) — сайдбар и карта с данными полностью
  отрисовались, ошибок в консоли нет (скриншот в рамках сессии);
- `healthcheck.py --base-url https://geobotany.of.by` (запущен на
  самом VPS, с доступом к `FRONTEND_DB_PASSWORD` из `deliver.env`):

```
[OK  ] wms_getmap: HTTP 200, PNG, 955 байт
[OK  ] wfs_getfeature: HTTP 200, 5 объектов, атрибуты непустые
[OK  ] main_page: HTTP 200, React-корень найден
[OK  ] year_district_json: HTTP 200, 1 лет, 7 пар год/район
[OK  ] db_matches_static: БД: 7 пар, файл: 7 пар

ИТОГ: всё в порядке
```

**Подтверждено**: витрина восстановлена, весь healthcheck зелёный.
