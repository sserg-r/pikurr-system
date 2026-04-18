# Развёртывание внешнего контура (REPIKURR)

Внешний контур — это серверная часть, которую видят пользователи.
Включает: PostGIS, GeoServer, React-фронтенд и nginx. Работает на сервере **192.168.251.190**.

---

## Архитектура

```
nginx (80) ──┬── / ──────────── React SPA (pikurr_srv_react)
             └── /geoserver/ ── GeoServer (pikurr_srv_geoserver :8090)
                                    └── PostGIS (pikurr_srv_postgis :5435)

inbox/ ── watchdog.py ── deliver.py ── PostGIS + GeoServer (обновление данных)
```

| Контейнер | Порт | Описание |
|---|---|---|
| `pikurr_srv_postgis` | 5435 | PostgreSQL + PostGIS |
| `pikurr_srv_geoserver` | 8090 | GeoServer |
| `pikurr_srv_react` | — | React SPA (без прямого порта) |
| `pikurr_srv_nginx` | 80 | Точка входа |

Сервисы:

| Адрес | Описание |
|---|---|
| http://192.168.251.190 | Веб-приложение (пользователи) |
| http://192.168.251.190:8090/geoserver/web | Панель GeoServer (admin/geoserver) |
| localhost:5435 | PostGIS (pikurr/pikurr/pikurr) |

---

## Требования

| Зависимость | Версия |
|---|---|
| Docker + Docker Compose v2 | ≥ 24 |
| Python 3 | ≥ 3.10 (для watchdog и deliver) |
| sudo | для systemd |
| rsync, git | для получения обновлений кода |

Зависимости для `deliver.py`:
```bash
pip3 install psycopg2-binary requests python-dotenv fiona shapely
# или через apt:
sudo apt install python3-psycopg2 python3-requests
```

---

## Первоначальное развёртывание

### 1. Клонировать репозиторий (sparse checkout)

На сервере нужна только папка `REPIKURR/`:

```bash
git clone --no-checkout https://github.com/sserg-r/pikurr-system.git ~/repikurr-repo
cd ~/repikurr-repo
git sparse-checkout init --cone
git sparse-checkout set REPIKURR
git checkout main
cp -r REPIKURR/. ~/repikurr/
```

Или, если репо уже клонирован полностью:
```bash
cd ~/repikurr-repo
git pull
cp -r REPIKURR/. ~/repikurr/
```

### 2. Создать `deliver.env`

```bash
cd ~/repikurr
cp deliver.env.example deliver.env
nano deliver.env   # заполнить реальными значениями
```

| Переменная | Значение |
|---|---|
| `FRONTEND_DB_USER/PASSWORD/NAME` | Данные PostGIS (pikurr/pikurr/pikurr) |
| `GEOSERVER_USER/PASSWORD` | Данные GeoServer (admin/geoserver) |
| `PIKURR_INBOX` | `/home/user/repikurr/inbox` |

### 3. Запустить деплой

```bash
cd ~/repikurr
bash deploy.sh
```

`deploy.sh` выполняет:
1. Останавливает старый стек
2. Создаёт директории `data/geodata/` и `inbox/`
3. Выставляет права на тома GeoServer
4. Поднимает контейнеры: `docker compose -f docker-compose.server.yml up -d --build`
5. Дожидается готовности GeoServer (до 120 сек)
6. Устанавливает и запускает systemd-сервис `pikurr-watchdog`

> **Полный сброс** (удалить данные PostGIS и растры):
> ```bash
> bash deploy.sh --clean
> ```

### 4. Проверить статус

```bash
docker compose -f docker-compose.server.yml ps
sudo systemctl status pikurr-watchdog
```

Открыть в браузере: **http://192.168.251.190** — должна открыться карта.

---

## Обновление кода фронтенда

При изменении React-приложения (без изменения данных):

```bash
cd ~/repikurr-repo
git pull
cp -r REPIKURR/. ~/repikurr/
cd ~/repikurr
bash deploy.sh
```

---

## Доставка данных (пакет обновлений)

Пакеты создаются ETL-контуром и доставляются через rsync.

### Автоматически (рекомендуется)

С машины администратора:
```bash
./package_and_push.sh
# или через дашборд: кнопка «ОТПРАВИТЬ ПАКЕТ НА СЕРВЕР»
```

### Вручную

```bash
rsync -avz outputs/dist/pikurr_update_*.zip user@192.168.251.190:~/repikurr/inbox/
```

### Что происходит после получения пакета

`watchdog.py` опрашивает `inbox/` каждые 10 секунд. При обнаружении нового `.zip` запускает `deliver.py`, который:

1. Распаковывает архив во временную директорию
2. Копирует TIF-файлы в `data/geodata/{year}/`
3. Загружает вектора (GeoPackage) в PostGIS через `ogr2ogr`
4. Пересоздаёт SQL-вьюхи из `create_assessment_schema.sql`
5. Перезагружает хранилища растров в GeoServer через REST API
6. Переименовывает ZIP в `delivered_<...>.zip` (не трогается повторно)

Логи доставки:
```bash
journalctl -fu pikurr-watchdog
# или
tail -f ~/repikurr/watchdog.log
```

---

## GeoServer: слои и стили

Конфигурация GeoServer хранится в `REPIKURR/geoserver_data/` и монтируется в контейнер.
**Ничего не настраивать вручную через веб-интерфейс** — все настройки в файлах.

| Слой | Источник | Назначение |
|---|---|---|
| `pikurr:fields` | VirtualTable → `assessment_ready` | Все годы с CQL-фильтрацией |
| `pikurr:fields_latest` | VirtualTable → `assessment_ready_latest` | Только свежайшая оценка |
| `pikurr:levelsagg` | VirtualTable → `agrifields` | Список землепользователей |
| `pikurr:image_assessment` | ImageMosaic → `data/geodata/2025/` | Растр последнего года |
| `pikurr:image_assessment_2024` | ImageMosaic → `data/geodata/2024/` | Растр 2024 |

Стили:
- `pikurr:agrifields1` — векторный слой полей (классификация по `valuation`)
- `pikurr:raster_vegetation` — растровый слой растительности

При добавлении нового года растров нужно:
1. Добавить новый ImageMosaic store через REST API (или вручную скопировать конфиг из `workspaces/pikurr/image_assessment_2024/`)
2. Добавить слой `image_assessment_{year}` в GeoServer

---

## PostGIS: схема базы данных

Таблицы (создаются `deliver.py` при первой доставке):

| Таблица | Описание |
|---|---|
| `agrifields` | Полигоны агрополей с атрибутами |
| `razgrafka` | Сетка трапеций |
| `assessment` | Статистика по полям (stats JSON, год) |

Вьюхи (пересоздаются при каждой доставке):

| Вьюха | Описание |
|---|---|
| `assessment_ready` | JOIN agrifields + assessment, все годы |
| `assessment_ready_latest` | То же, только свежайший год на поле |

Подключение для диагностики:
```bash
psql -h localhost -p 5435 -U pikurr -d pikurr
```

---

## nginx

Конфигурация: `REPIKURR/nginx.local.conf`

- `/` → React SPA (проксируется в `react-client`)
- `/geoserver/` → GeoServer (проксируется в `geoserver:8080`)

---

## Диагностика

```bash
# Статус контейнеров
docker compose -f ~/repikurr/docker-compose.server.yml ps

# Логи GeoServer
docker logs pikurr_srv_geoserver -f

# Логи nginx
docker logs pikurr_srv_nginx -f

# Статус и логи watchdog
sudo systemctl status pikurr-watchdog
journalctl -fu pikurr-watchdog

# Перезапуск watchdog вручную
sudo systemctl restart pikurr-watchdog

# Проверить что GeoServer отвечает
curl -s -u admin:geoserver http://localhost:8090/geoserver/rest/workspaces.json | python3 -m json.tool

# Проверить подключение к PostGIS
psql -h localhost -p 5435 -U pikurr -d pikurr -c "SELECT COUNT(*) FROM assessment;"
```

---

## Типичные проблемы

### GeoServer не отдаёт тайлы после обновления растров

GeoServer кэширует ImageMosaic. После доставки нового пакета `deliver.py` автоматически
сбрасывает кэш через REST API. Если этого не произошло — сбросить вручную:

```bash
curl -X DELETE -u admin:geoserver \
  http://localhost:8090/geoserver/rest/workspaces/pikurr/coveragestores/image_assessment/coverages/image_assessment/reset
```

### Watchdog не подхватывает пакет

```bash
# Проверить что сервис запущен
sudo systemctl status pikurr-watchdog

# Проверить что файл в inbox
ls -la ~/repikurr/inbox/

# Запустить deliver.py вручную
cd ~/repikurr
source deliver.env
python3 deliver.py ~/repikurr/inbox/pikurr_update_*.zip
```

### PostGIS недоступен

```bash
docker logs pikurr_srv_postgis
docker compose -f ~/repikurr/docker-compose.server.yml restart postgis
```
